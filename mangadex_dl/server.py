"""Tankōbon — the local web app. `python3 -m mangadex_dl serve`

Stdlib only: ThreadingHTTPServer + a JSON API + Server-Sent Events for live progress.
Listens on 127.0.0.1 only.
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import mimetypes
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import uuid
import webbrowser
import zipfile
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import __version__, adfilter, api, engine
from .auth import AuthError, Session
from .engine import Series

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
CACHE_DIR = os.path.expanduser("~/.cache/mangadex-dl")
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
               ".gif": "image/gif", ".webp": "image/webp"}


class HttpError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


# ====================================================================== live events

class Hub:
    """Fan-out of JSON events to every connected SSE client."""

    def __init__(self):
        self.subs: set = set()
        self.lock = threading.Lock()

    def subscribe(self) -> "queue.Queue[dict]":
        q: "queue.Queue[dict]" = queue.Queue(maxsize=2000)
        with self.lock:
            self.subs.add(q)
        return q

    def unsubscribe(self, q) -> None:
        with self.lock:
            self.subs.discard(q)

    def emit(self, ev: dict) -> None:
        with self.lock:
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass


class LRU:
    def __init__(self, size: int):
        self.size = size
        self.d: "OrderedDict[str, Any]" = OrderedDict()
        self.lock = threading.Lock()

    def put(self, k: str, v: Any) -> None:
        with self.lock:
            self.d[k] = v
            self.d.move_to_end(k)
            while len(self.d) > self.size:
                self.d.popitem(last=False)

    def get(self, k: str) -> Any:
        with self.lock:
            return self.d.get(k)


class TTLCache:
    def __init__(self, ttl: float):
        self.ttl = ttl
        self.d: Dict[str, Tuple[float, Any]] = {}
        self.lock = threading.Lock()

    def get(self, k: str, make: Callable[[], Any]) -> Any:
        with self.lock:
            hit = self.d.get(k)
            if hit and time.time() - hit[0] < self.ttl:
                return hit[1]
        v = make()
        with self.lock:
            self.d[k] = (time.time(), v)
        return v

    def drop(self, k: str) -> None:
        with self.lock:
            self.d.pop(k, None)


# ====================================================================== download queue

class Task:
    def __init__(self, series: Series, job: engine.Job, lang: str, data_saver: bool,
                 clean: bool = True, remove: Optional[engine.RemoveMap] = None):
        self.clean, self.remove = clean, remove
        self.id = uuid.uuid4().hex[:10]
        self.series, self.job, self.lang, self.data_saver = series, job, lang, data_saver
        self.status = "queued"
        self.pages_done = 0
        self.pages_total = job.pages
        self.bytes = 0
        self.error = ""
        self.started = self.finished = 0.0
        self.cancel = threading.Event()
        self.current = ""

    def to_dict(self, out_root: str) -> Dict[str, Any]:
        return {
            "id": self.id, "manga_id": self.series.id, "series": self.series.title,
            "name": self.job.name, "file": os.path.relpath(self.job.path, out_root),
            "status": self.status, "pages_done": self.pages_done, "pages_total": self.pages_total,
            "bytes": self.bytes, "error": self.error, "started": self.started,
            "finished": self.finished, "current": self.current,
            "chapter_ids": [c["id"] for c in self.job.chapters],
            "volume": self.job.volume, "removed": self.job.removed,
            "cover": proxy(self.series.cover_url) if self.series.cover_url else None,
        }


class Review:
    """The pre-bind proofing pass: read every page of the selected volumes, run the ad detector,
    and stream verdicts to the UI chapter by chapter. Pages land in the page cache, so the bind
    afterwards doesn't download anything twice (it's mostly just zipping by then)."""

    def __init__(self, app: "App", series: Series, chapters: List[Dict[str, Any]], volumes: List[str],
                 lang: str, data_saver: bool, group: str):
        self.id = uuid.uuid4().hex[:10]
        self.app, self.series, self.chapters = app, series, chapters
        self.volumes, self.lang, self.data_saver, self.group = volumes, lang, data_saver, group
        self.status, self.error, self.done = "running", "", 0
        self.page_done = self.page_total = 0
        self.cancel = threading.Event()
        self.pages: List[adfilter.Page] = []
        self.rows: List[Dict[str, Any]] = []
        self.verdicts: Dict[Any, Any] = {}
        threading.Thread(target=self._run, daemon=True, name=f"review-{self.id}").start()

    def fp(self, cid: str, filename: str) -> Optional[adfilter.Fingerprint]:
        return next((p.fp for p in self.pages if p.chapter_id == cid and p.filename == filename), None)

    def _emit(self) -> None:
        self.app.hub.emit({"type": "review", "review": self.to_dict()})

    def _run(self) -> None:
        try:
            with ThreadPoolExecutor(max_workers=4) as ex:
                for k, c in enumerate(self.chapters):
                    if self.cancel.is_set():
                        self.status = "cancelled"
                        break
                    cid = c["id"]
                    urls = api.get_page_urls(cid, self.data_saver)
                    n = len(urls)
                    self.page_done, self.page_total = 0, n
                    futs = {ex.submit(engine.fetch_page, cid, u, True): i for i, u in enumerate(urls)}
                    fps: Dict[int, Optional[adfilter.Fingerprint]] = {}
                    for fut in as_completed(futs):
                        if self.cancel.is_set():
                            break
                        fps[futs[fut]] = adfilter.fingerprint(fut.result())
                        self.page_done += 1
                        if self.page_done % 6 == 0:
                            self._emit()
                    if self.cancel.is_set():
                        self.status = "cancelled"
                        break
                    for i in range(n):
                        self.pages.append(adfilter.Page(cid, i, n, os.path.basename(urls[i]), fps.get(i)))
                    self.rows.append({"id": cid, "label": engine.chapter_label(c),
                                      "volume": c["attributes"].get("volume"), "total": n})
                    self.verdicts = adfilter.analyze(self.pages, self.app.blocklist)
                    self.done = k + 1
                    self._emit()
            if self.status == "running":
                self.status = "done"
        except Exception as e:
            self.status, self.error = "error", str(e) or e.__class__.__name__
        self._emit()

    def to_dict(self) -> Dict[str, Any]:
        by_ch: Dict[str, List[Dict[str, Any]]] = {}
        for p in self.pages:
            v, why = self.verdicts.get((p.chapter_id, p.index), ("keep", ""))
            # Send flagged pages plus a little context from each end; the rest are story pages.
            context = p.index < adfilter.HEAD or p.index >= p.total - adfilter.TAIL
            if v == "keep" and not context:
                continue
            by_ch.setdefault(p.chapter_id, []).append({
                "index": p.index, "filename": p.filename, "verdict": v, "reason": why,
                "w": p.fp.w if p.fp else None, "h": p.fp.h if p.fp else None,
                "img": f"/api/review/{self.id}/img/{p.chapter_id}/{urllib.parse.quote(p.filename)}",
            })
        return {"id": self.id, "manga_id": self.series.id, "status": self.status, "error": self.error,
                "done": self.done, "total": len(self.chapters), "volumes": self.volumes,
                "page_done": self.page_done, "page_total": self.page_total,
                "chapters": [dict(r, pages=by_ch.get(r["id"], [])) for r in self.rows]}


class Downloader:
    """One worker thread, one file at a time — keeps us well inside MangaDex's rate limits."""

    def __init__(self, app: "App"):
        self.app = app
        self.tasks: "OrderedDict[str, Task]" = OrderedDict()
        self.q: "queue.Queue[str]" = queue.Queue()
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True, name="downloader").start()

    def add(self, tasks: List[Task]) -> None:
        with self.lock:
            for t in tasks:
                self.tasks[t.id] = t
        for t in tasks:
            self.q.put(t.id)
        self.app.hub.emit({"type": "queued", "tasks": [self.dict(t) for t in tasks]})

    def dict(self, t: Task) -> Dict[str, Any]:
        return t.to_dict(self.app.out_root)

    def snapshot(self) -> List[Dict[str, Any]]:
        with self.lock:
            return [self.dict(t) for t in self.tasks.values()]

    def cancel(self, tid: str) -> None:
        t = self.tasks.get(tid)
        if not t:
            raise HttpError(404, "no such task")
        t.cancel.set()
        if t.status == "queued":
            t.status = "cancelled"
            self.app.hub.emit({"type": "task", "task": self.dict(t)})

    def cancel_all(self) -> None:
        for t in list(self.tasks.values()):
            if t.status in ("queued", "running"):
                self.cancel(t.id)

    def clear(self) -> None:
        with self.lock:
            for k in [k for k, t in self.tasks.items() if t.status in ("done", "error", "cancelled")]:
                del self.tasks[k]
        self.app.hub.emit({"type": "cleared"})

    def _loop(self) -> None:
        while True:
            t = self.tasks.get(self.q.get())
            if not t or t.cancel.is_set():
                continue
            t.status, t.started = "running", time.time()
            self.app.hub.emit({"type": "task", "task": self.dict(t)})

            def on_page(c, done, total, idx, ext, data, t=t):
                t.pages_done += 1
                t.bytes += len(data)
                t.pages_total = max(t.pages_total, t.pages_done)
                t.current = engine.chapter_label(c)
                n = t.pages_done
                self.app.live.put(f"{t.id}/{n}", (IMAGE_TYPES.get(ext.lower(), "image/jpeg"), data))
                self.app.hub.emit({
                    "type": "page", "task": t.id, "chapter": c["id"], "label": t.current,
                    "chapter_done": done, "chapter_total": total, "done": n,
                    "total": t.pages_total, "bytes": t.bytes, "img": f"/api/live/{t.id}/{n}",
                })
            try:
                t.pages_done = 0
                engine.run_job(t.job, t.series, lang=t.lang, data_saver=t.data_saver,
                               workers=4, on_page=on_page, cancel=t.cancel,
                               clean=t.clean, remove=t.remove, blocklist=self.app.blocklist)
                t.status = "done"
            except engine.Cancelled:
                t.status = "cancelled"
            except Exception as e:
                t.status, t.error = "error", str(e) or e.__class__.__name__
            t.finished = time.time()
            self.app.hub.emit({"type": "task", "task": self.dict(t)})
            if t.status == "done":
                self.app.hub.emit({"type": "library"})


# ====================================================================== app state

def proxy(url: Optional[str]) -> Optional[str]:
    return "/api/img?u=" + urllib.parse.quote(url, safe="") if url else None


def names(m: Dict[str, Any], t: str) -> List[str]:
    return [r["attributes"]["name"] for r in api.related(m, t) if r.get("attributes")]


def manga_card(m: Dict[str, Any], lang: str = "en") -> Dict[str, Any]:
    a = m["attributes"]
    return {
        "id": m["id"],
        "title": api.pick_title(a, lang),
        "year": a.get("year"),
        "status": a.get("status"),
        "contentRating": a.get("contentRating"),
        "demographic": a.get("publicationDemographic"),
        "tags": [api.pick_text(t["attributes"]["name"]) for t in a.get("tags", [])
                 if t["attributes"].get("group") in ("genre", "theme")][:6],
        "authors": names(m, "author"),
        "cover": proxy(api.cover_url(m, 256)),
        "cover_lg": proxy(api.cover_url(m, 512)),
        "description": api.pick_text(a.get("description"), lang)[:400],
        "languages": a.get("availableTranslatedLanguages") or [],
        "originalLanguage": a.get("originalLanguage"),
    }


class App:
    def __init__(self, out_root: str):
        self.out_root = os.path.abspath(os.path.expanduser(out_root))
        os.makedirs(self.out_root, exist_ok=True)
        self.hub = Hub()
        self.live = LRU(80)
        self.session = Session()
        self.manga_cache = TTLCache(600)
        self.chapter_cache = TTLCache(300)
        self.account_cache = TTLCache(120)
        self.cover_cache = TTLCache(3600)
        self.blocklist = adfilter.Blocklist()
        self.reviews: "OrderedDict[str, Review]" = OrderedDict()
        shutil.rmtree(engine.PAGE_CACHE, ignore_errors=True)  # stale review pages from last run
        self.downloader = Downloader(self)
        self.port = 0

    # ------------------------------------------------------------ mangadex
    def manga(self, mid: str) -> Dict[str, Any]:
        return self.manga_cache.get(mid, lambda: api.get_manga(mid))

    def raw_chapters(self, mid: str, lang: str) -> List[Dict[str, Any]]:
        return self.chapter_cache.get(f"{mid}:{lang}", lambda: api.iter_chapters(mid, [lang]))

    def volume_covers(self, mid: str, lang: str) -> Dict[str, str]:
        def make():
            orig = self.manga(mid)["attributes"].get("originalLanguage") or "ja"
            try:
                return api.get_volume_covers(mid, [lang, orig])
            except api.ApiError:
                return {}
        return self.cover_cache.get(f"{mid}:{lang}", make)

    def search(self, q: str) -> Dict[str, Any]:
        q = q.strip()
        if not q:
            raise HttpError(400, "empty query")
        t = api.parse_target(q)
        if t and t["kind"] == "chapter":
            c = api.get_chapter(t["id"])
            rel = api.related(c, "manga")
            if not rel:
                raise HttpError(404, "chapter has no manga")
            return {"kind": "manga", "id": rel[0]["id"], "chapter": t["id"],
                    "lang": c["attributes"].get("translatedLanguage")}
        if t:
            return {"kind": "manga", "id": t["id"]}
        return {"kind": "results", "results": [manga_card(m) for m in api.search_manga(q, 18)]}

    def manga_detail(self, mid: str) -> Dict[str, Any]:
        m = self.manga(mid)
        a = m["attributes"]
        stats = api.get_statistics(mid)
        series = Series(m)
        folder = series.folder(self.out_root)
        card = manga_card(m)
        card.update({
            "description": api.pick_text(a.get("description")),
            "altTitles": [{"lang": k, "title": v} for t in (a.get("altTitles") or []) for k, v in t.items()],
            "artists": names(m, "artist"),
            "cover_full": proxy(api.cover_url(m, 0)),
            "tags_all": [{"name": api.pick_text(t["attributes"]["name"]), "group": t["attributes"].get("group")}
                         for t in a.get("tags", [])],
            "lastChapter": a.get("lastChapter"), "lastVolume": a.get("lastVolume"),
            "stats": {"rating": ((stats.get("rating") or {}).get("bayesian")),
                      "follows": stats.get("follows"),
                      "comments": ((stats.get("comments") or {}).get("repliesCount"))},
            "url": f"https://mangadex.org/title/{mid}",
            "local_dir": os.path.relpath(folder, self.out_root) if os.path.isdir(folder) else None,
            "following": None,
        })
        return card

    def chapters(self, mid: str, lang: str, group: str = "", all_versions: bool = False) -> Dict[str, Any]:
        raw = self.raw_chapters(mid, lang)
        picked = engine.choose_versions(raw, group or None, all_versions)
        series = Series(self.manga(mid))
        have = engine.downloaded_chapters(series.folder(self.out_root))
        versions: Dict[str, int] = {}
        for c in raw:
            k = c["attributes"].get("chapter") or c["id"]
            versions[k] = versions.get(k, 0) + 1
        out = []
        for c in picked:
            a = c["attributes"]
            out.append({
                "id": c["id"], "chapter": a.get("chapter"), "volume": a.get("volume"),
                "title": a.get("title") or "", "pages": a.get("pages", 0),
                "groups": api.group_names(c), "date": a.get("readableAt") or a.get("publishAt"),
                "label": engine.chapter_label(c),
                "downloaded": c["id"] in have["ids"] or (lang, a.get("chapter")) in have["numbers"],
                "versions": versions.get(a.get("chapter") or c["id"], 1),
            })
        # Volumes are the unit of download. Chapters with no volume yet are "stragglers".
        covers = self.volume_covers(mid, lang)
        have_vols = engine.downloaded_volumes(series.folder(self.out_root))
        vols: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
        for c in picked:
            v = c["attributes"].get("volume")
            if v:
                vols.setdefault(v, []).append(c)

        def vkey(v: str):
            try:
                return (0, float(v))
            except ValueError:
                return (1, 0.0)
        volumes = []
        order = sorted(vols, key=vkey)
        for k, v in enumerate(order):
            chs = vols[v]
            nxt = [engine.chapter_num(c) for c in vols[order[k + 1]]] if k + 1 < len(order) else []
            next_first = min((n for n in nxt if n is not None), default=None)
            cover = covers.get(api.vol_key(v))
            volumes.append({
                "volume": v, "label": engine.volume_label(v),
                "chapter_ids": [c["id"] for c in chs],
                "first": chs[0]["attributes"].get("chapter"), "last": chs[-1]["attributes"].get("chapter"),
                "count": len(chs), "pages": sum(c["attributes"].get("pages", 0) for c in chs),
                "cover": proxy(cover + ".256.jpg") if cover else None,
                "cover_lg": proxy(cover + ".512.jpg") if cover else None,
                "downloaded": api.vol_key(v) in have_vols,
                "gaps": engine.volume_gaps(chs, next_first)[:12],
                "groups": sorted({g for c in chs for g in api.group_names(c)}),
            })
        stragglers = [x for x in out if not x["volume"]]
        return {"chapters": out, "volumes": volumes, "stragglers": stragglers, "lang": lang,
                "groups": [{"name": g, "count": n} for g, n in engine.group_counts(raw).most_common()]}

    def _volume_chapters(self, body: Dict[str, Any]):
        mid = body.get("manga_id") or ""
        lang = body.get("lang") or "en"
        wanted = {str(v) for v in (body.get("volumes") or [])}
        if not wanted:
            raise HttpError(400, "pick at least one volume")
        raw = self.raw_chapters(mid, lang)
        full = engine.choose_versions(raw, body.get("group") or None)
        chosen = [c for c in full if c["attributes"].get("volume") in wanted]
        if not chosen:
            raise HttpError(400, "those volumes aren't available any more — reload")
        return mid, lang, full, chosen, Series(self.manga(mid), lang)

    def start_review(self, body: Dict[str, Any]) -> Dict[str, Any]:
        if not adfilter.HAS_PIL:
            raise HttpError(501, "Page review needs Pillow: pip install pillow")
        mid, lang, _, chosen, series = self._volume_chapters(body)
        for r in self.reviews.values():
            r.cancel.set()
        rv = Review(self, series, chosen, [str(v) for v in body.get("volumes") or []], lang,
                    bool(body.get("data_saver")), body.get("group") or "")
        self.reviews[rv.id] = rv
        while len(self.reviews) > 5:
            self.reviews.popitem(last=False)
        return rv.to_dict()

    def learn(self, rv: "Review", remove: engine.RemoveMap, keep: engine.RemoveMap) -> int:
        """Remember removed pages; forget learned pages the user chose to keep."""
        learned = 0
        groups = {c["id"]: ", ".join(api.group_names(c)) for c in rv.chapters}
        for cid, names in remove.items():
            for fn in names:
                fp = rv.fp(cid, fn)
                if fp and self.blocklist.add(fp, groups.get(cid, ""), rv.series.title):
                    learned += 1
        for cid, names in keep.items():
            for fn in names:
                fp = rv.fp(cid, fn)
                if fp:
                    self.blocklist.forget(fp)
        return learned

    def download(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Bind whole volumes: every chapter MangaDex has tagged with each requested volume.
        With a review_id, exactly the pages the user ticked are removed; otherwise `clean`
        (default on) auto-removes pages the detector is confident about."""
        mid, lang, full, chosen, series = self._volume_chapters(body)
        remove: Optional[engine.RemoveMap] = None
        learned = 0
        rv = self.reviews.get(body.get("review_id") or "")
        if rv is not None:
            as_map = lambda d: {str(k): {os.path.basename(str(x)) for x in v} for k, v in (d or {}).items()}
            remove = as_map(body.get("remove"))
            if body.get("remember", True):
                learned = self.learn(rv, remove, as_map(body.get("keep")))
        jobs = engine.plan_jobs(series, chosen, self.out_root, "volume", full,
                                include_loose=False, covers=self.volume_covers(mid, lang))
        force = bool(body.get("force"))
        queued = [j for j in jobs if force or not j.exists]
        skipped = [j.name for j in jobs if not (force or not j.exists)]
        clean = bool(body.get("clean", True))
        tasks = [Task(series, j, lang, bool(body.get("data_saver")), clean, remove) for j in queued]
        if tasks:
            self.downloader.add(tasks)
        return {"tasks": [self.downloader.dict(t) for t in tasks], "skipped": skipped, "learned": learned}

    # ------------------------------------------------------------ account
    def account(self, kind: str, lang: str = "en") -> Any:
        s = self.session
        if not s.logged_in:
            raise HttpError(401, "not logged in")
        if kind == "follows":
            def make():
                follows = s.follows()
                try:
                    statuses = s.reading_statuses()
                except api.ApiError:
                    statuses = {}
                cards = []
                for m in follows:
                    c = manga_card(m)
                    c["reading_status"] = statuses.get(m["id"])
                    cards.append(c)
                return {"manga": cards}
            return self.account_cache.get("follows", make)
        if kind == "updates":
            def make_updates():
                feed = s.updates([lang])
                mids = list(OrderedDict.fromkeys(r["id"] for c in feed for r in api.related(c, "manga")))
                covers = {m["id"]: manga_card(m) for m in api.get_manga_batch(mids)} if mids else {}
                out = []
                for c in feed:
                    a = c["attributes"]
                    rel = api.related(c, "manga")
                    mid = rel[0]["id"] if rel else None
                    out.append({"id": c["id"], "chapter": a.get("chapter"), "volume": a.get("volume"),
                                "title": a.get("title") or "", "pages": a.get("pages"),
                                "date": a.get("readableAt"), "groups": api.group_names(c),
                                "label": engine.chapter_label(c), "lang": a.get("translatedLanguage"),
                                "manga": covers.get(mid) or {"id": mid, "title": "?"}})
                return out
            return self.account_cache.get(f"updates:{lang}", make_updates)
        if kind == "lists":
            def make_lists():
                out = []
                for lst in s.lists():
                    mids = [r["id"] for r in lst.get("relationships", []) if r["type"] == "manga"]
                    cards = [manga_card(m) for m in api.get_manga_batch(mids)] if mids else []
                    out.append({"id": lst["id"], "name": lst["attributes"].get("name"),
                                "visibility": lst["attributes"].get("visibility"), "manga": cards})
                return out
            return self.account_cache.get("lists", make_lists)
        raise HttpError(404, "unknown")

    # ------------------------------------------------------------ library
    def library(self) -> List[Dict[str, Any]]:
        out = []
        for d in sorted(os.listdir(self.out_root)):
            folder = os.path.join(self.out_root, d)
            if not os.path.isdir(folder) or d.startswith("."):
                continue
            files = []
            meta = engine.read_meta(folder)
            mfiles = meta.get("files") or {}
            for fn in sorted(os.listdir(folder)):
                if not fn.lower().endswith(".cbz"):
                    continue
                st = os.stat(os.path.join(folder, fn))
                info = mfiles.get(fn) or {}
                files.append({"name": fn, "path": f"{d}/{fn}", "size": st.st_size, "mtime": st.st_mtime,
                              "pages": info.get("pages"), "volume": info.get("volume"),
                              "chapters": [c.get("chapter") for c in info.get("chapters", [])]})
            if not files:
                continue
            has_cover = os.path.exists(os.path.join(folder, engine.COVER_FILE))
            out.append({"dir": d, "title": meta.get("title") or d, "manga_id": meta.get("manga_id"),
                        "writer": meta.get("writer"),
                        "cover": f"api/library/cover?d={urllib.parse.quote(d)}" if has_cover else None,
                        "files": files, "size": sum(f["size"] for f in files),
                        "updated": max(f["mtime"] for f in files)})
        out.sort(key=lambda s: -s["updated"])
        return out

    def safe_path(self, rel: str, must_exist: bool = True) -> str:
        p = os.path.realpath(os.path.join(self.out_root, rel or ""))
        root = os.path.realpath(self.out_root)
        if not (p == root or p.startswith(root + os.sep)):
            raise HttpError(403, "outside library")
        if must_exist and not os.path.exists(p):
            raise HttpError(404, "not found")
        return p

    def cbz_pages(self, rel: str) -> Tuple[str, List[str]]:
        p = self.safe_path(rel)
        if not p.lower().endswith(".cbz"):
            raise HttpError(400, "not a cbz")
        with zipfile.ZipFile(p) as z:
            pages = sorted(n for n in z.namelist()
                           if os.path.splitext(n)[1].lower() in IMAGE_TYPES and not n.startswith("__MACOSX"))
        return p, pages

# ====================================================================== HTTP

def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = f"Tankobon/{__version__}"

        def log_message(self, fmt, *args):  # quiet
            pass

        # ---------------------------------------------------- responses
        def send_bytes(self, data: bytes, ctype: str, code: int = 200,
                       headers: Optional[Dict[str, str]] = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def send_json(self, obj: Any, code: int = 200) -> None:
            self.send_bytes(json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8",
                            code, {"Cache-Control": "no-store"})

        def send_file(self, path: str, ctype: Optional[str] = None, attachment: bool = False,
                      cache: str = "no-cache") -> None:
            size = os.path.getsize(path)
            ctype = ctype or mimetypes.guess_type(path)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", cache)
            if attachment:
                fn = os.path.basename(path)
                self.send_header("Content-Disposition",
                                 "attachment; filename*=UTF-8''" + urllib.parse.quote(fn))
            self.end_headers()
            if self.command == "HEAD":
                return
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(256 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)

        def body(self) -> Dict[str, Any]:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 1_000_000:
                raise HttpError(413, "too big")
            raw = self.rfile.read(n) if n else b"{}"
            try:
                return json.loads(raw.decode() or "{}")
            except ValueError:
                raise HttpError(400, "bad json")

        # ---------------------------------------------------- dispatch
        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def _dispatch(self, method: str) -> None:
            u = urllib.parse.urlsplit(self.path)
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            try:
                self._guard(method)
                self._local(method, u.path, q)
            except HttpError as e:
                self._err(e.code, str(e))
            except AuthError as e:
                self._err(401, str(e))
            except api.ApiError as e:
                self._err(502, str(e))
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:
                traceback.print_exc()
                self._err(500, f"{e.__class__.__name__}: {e}")

        def _err(self, code: int, msg: str) -> None:
            try:
                self.send_json({"error": msg}, code)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _guard(self, method: str) -> None:
            """Only answer browsers that are really talking to localhost (blocks DNS rebinding)
            and only accept writes from our own page (blocks cross-site POSTs)."""
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            if host not in ("localhost", "127.0.0.1", "::1"):
                raise HttpError(403, "bad host")
            if method == "POST":
                origin = self.headers.get("Origin")
                if origin:
                    oh = urllib.parse.urlsplit(origin).hostname
                    if oh not in ("localhost", "127.0.0.1", "::1"):
                        raise HttpError(403, "bad origin")
                if "application/json" not in (self.headers.get("Content-Type") or ""):
                    raise HttpError(415, "json only")

        # ---------------------------------------------------- local (full) API
        def _local(self, method: str, path: str, q: Dict[str, str]) -> None:
            if method == "GET" and (path == "/" or not path.startswith("/api/")):
                return self._static(path)
            if method == "GET":
                if path == "/api/state":
                    return self.send_json({
                        "version": __version__, "out_dir": app.out_root,
                        "logged_in": app.session.logged_in, "username": app.session.username,
                        "tasks": app.downloader.snapshot(),
                        "ads": {"available": adfilter.HAS_PIL, "learned": len(app.blocklist)}})
                if path == "/api/events":
                    return self._events()
                if path == "/api/search":
                    return self.send_json(app.search(q.get("q", "")))
                m = re.fullmatch(r"/api/manga/([0-9a-f-]{36})", path)
                if m:
                    return self.send_json(app.manga_detail(m.group(1)))
                m = re.fullmatch(r"/api/manga/([0-9a-f-]{36})/chapters", path)
                if m:
                    return self.send_json(app.chapters(m.group(1), q.get("lang", "en"),
                                                       q.get("group", ""), q.get("all") == "1"))
                m = re.fullmatch(r"/api/review/([0-9a-f]+)", path)
                if m:
                    rv = app.reviews.get(m.group(1))
                    if not rv:
                        raise HttpError(404, "review expired")
                    return self.send_json(rv.to_dict())
                m = re.fullmatch(r"/api/review/([0-9a-f]+)/img/([0-9a-f-]{36})/([^/]+)", path)
                if m:
                    rv = app.reviews.get(m.group(1))
                    if not rv:
                        raise HttpError(404, "review expired")
                    fn = os.path.basename(urllib.parse.unquote(m.group(3)))
                    p = engine.cached_page_path(m.group(2), fn, rv.data_saver)
                    if not os.path.isfile(p):
                        raise HttpError(404, "page not cached")
                    return self.send_file(p, IMAGE_TYPES.get(os.path.splitext(fn)[1].lower(), "image/jpeg"),
                                          cache="max-age=3600")
                m = re.fullmatch(r"/api/live/([0-9a-f]+)/(\d+)", path)
                if m:
                    hit = app.live.get(f"{m.group(1)}/{m.group(2)}")
                    if not hit:
                        raise HttpError(404, "gone")
                    return self.send_bytes(hit[1], hit[0], headers={"Cache-Control": "max-age=3600"})
                if path == "/api/img":
                    return self._img(q.get("u", ""))
                if path == "/api/tasks":
                    return self.send_json(app.downloader.snapshot())
                if path.startswith("/api/me/"):
                    return self.send_json(app.account(path[len("/api/me/"):], q.get("lang", "en")))
                if self._library_get(path, q):
                    return
            if method == "POST":
                b = self.body()
                if path == "/api/download":
                    return self.send_json(app.download(b))
                m = re.fullmatch(r"/api/tasks/([0-9a-f]+)/cancel", path)
                if m:
                    app.downloader.cancel(m.group(1))
                    return self.send_json({"ok": True})
                if path == "/api/tasks/cancel-all":
                    app.downloader.cancel_all()
                    return self.send_json({"ok": True})
                if path == "/api/review":
                    return self.send_json(app.start_review(b))
                m = re.fullmatch(r"/api/review/([0-9a-f]+)/cancel", path)
                if m:
                    rv = app.reviews.get(m.group(1))
                    if rv:
                        rv.cancel.set()
                    return self.send_json({"ok": True})
                if path == "/api/blocklist/clear":
                    app.blocklist.clear()
                    return self.send_json({"learned": 0})
                if path == "/api/tasks/clear":
                    app.downloader.clear()
                    return self.send_json({"ok": True})
                if path == "/api/login":
                    fields = [str(b.get(k) or "").strip() for k in
                              ("username", "password", "client_id", "client_secret")]
                    if not all(fields):
                        raise HttpError(400, "all four fields are required")
                    app.session.login(*fields)
                    app.account_cache = TTLCache(120)
                    return self.send_json({"logged_in": True, "username": app.session.username})
                if path == "/api/logout":
                    app.session.logout()
                    app.account_cache = TTLCache(120)
                    return self.send_json({"logged_in": False})
                if path == "/api/reveal":
                    p = app.safe_path(b.get("path", ""))
                    if sys.platform == "darwin":
                        subprocess.Popen(["open", "-R", p])
                    elif os.name == "nt":
                        subprocess.Popen(["explorer", "/select,", p])
                    else:
                        subprocess.Popen(["xdg-open", os.path.dirname(p) if os.path.isfile(p) else p])
                    return self.send_json({"ok": True})
            raise HttpError(404, "not found")

        def _library_get(self, path: str, q: Dict[str, str]) -> bool:
            """Read-only library routes."""
            if path == "/api/library":
                self.send_json({"series": app.library(), "out_dir": app.out_root})
                return True
            if path == "/api/library/cover":
                p = app.safe_path(os.path.join(q.get("d", ""), engine.COVER_FILE))
                self.send_file(p, "image/jpeg", cache="max-age=86400")
                return True
            if path == "/api/file":
                p = app.safe_path(q.get("p", ""))
                if not p.lower().endswith(".cbz"):
                    raise HttpError(400, "not a cbz")
                self.send_file(p, "application/vnd.comicbook+zip", attachment=True)
                return True
            if path == "/api/read":
                _, pages = app.cbz_pages(q.get("p", ""))
                self.send_json({"pages": len(pages)})
                return True
            if path == "/api/page":
                p, pages = app.cbz_pages(q.get("p", ""))
                n = int(q.get("n", "0"))
                if not 0 <= n < len(pages):
                    raise HttpError(404, "no such page")
                with zipfile.ZipFile(p) as z:
                    data = z.read(pages[n])
                self.send_bytes(data, IMAGE_TYPES.get(os.path.splitext(pages[n])[1].lower(), "image/jpeg"),
                                headers={"Cache-Control": "max-age=3600"})
                return True
            return False

        def _static(self, path: str) -> None:
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            p = os.path.realpath(os.path.join(WEB_DIR, rel))
            if not p.startswith(os.path.realpath(WEB_DIR) + os.sep) or not os.path.isfile(p):
                raise HttpError(404, "not found")
            ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self.send_file(p, ctype)

        def _img(self, url: str) -> None:
            u = urllib.parse.urlsplit(url)
            if u.scheme != "https" or u.hostname != "uploads.mangadex.org" or not u.path.startswith("/covers/"):
                raise HttpError(400, "only MangaDex covers can be proxied")
            os.makedirs(os.path.join(CACHE_DIR, "img"), exist_ok=True)
            cp = os.path.join(CACHE_DIR, "img", hashlib.sha1(url.encode()).hexdigest())
            if not os.path.exists(cp):
                data = api.fetch(url, retries=2)
                with open(cp + ".tmp", "wb") as f:
                    f.write(data)
                os.replace(cp + ".tmp", cp)
            ext = os.path.splitext(u.path)[1].lower()
            self.send_file(cp, IMAGE_TYPES.get(ext, "image/jpeg"), cache="max-age=604800")

        def _events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            sub = app.hub.subscribe()
            try:
                self.wfile.write(b"retry: 2000\n\n")
                self.wfile.flush()
                while True:
                    try:
                        ev = sub.get(timeout=15)
                        self.wfile.write(b"data: " + json.dumps(ev, ensure_ascii=False).encode() + b"\n\n")
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                app.hub.unsubscribe(sub)

    return Handler


# ====================================================================== main

class Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        # Browsers drop idle keep-alive connections all the time; that's not an error.
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError,
                                          ConnectionAbortedError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def already_running(port: int) -> bool:
    """Is a Tankōbon already answering on this port?"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/api/state", timeout=1.5) as r:
            return "out_dir" in json.loads(r.read().decode())
    except Exception:
        return False


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="mangadex-dl serve", description="Run the Tankōbon web app.")
    p.add_argument("-p", "--port", type=int, default=8787)
    p.add_argument("-o", "--out", default="downloads", help="library folder (default: ./downloads)")
    p.add_argument("--no-open", action="store_true", help="don't open a browser tab")
    args = p.parse_args(argv)

    try:
        probe = Server(("127.0.0.1", args.port), BaseHTTPRequestHandler)
        probe.server_close()
        port = args.port
    except OSError:
        if already_running(args.port):
            url = f"http://localhost:{args.port}/"
            print(f"\n  単  Tankōbon is already running → {url}\n     (stop that one with Ctrl-C first "
                  f"if you want to restart it)\n")
            if not args.no_open:
                webbrowser.open(url)
            return 0
        port = 0
        print(f"  Port {args.port} is taken by another program, so using a free one instead.")

    app = App(args.out)
    srv = Server(("127.0.0.1", port), make_handler(app))
    app.port = srv.server_address[1]
    url = f"http://localhost:{app.port}/"
    print(f"\n  単  Tankōbon is running → {url}\n     library: {app.out_root}\n     Ctrl-C to stop\n", flush=True)
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye!")
    finally:
        app.downloader.cancel_all()
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
