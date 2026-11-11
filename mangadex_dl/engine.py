"""Download engine shared by the CLI and the web app.

Chapter selection, output naming, downloading pages and writing .cbz files, plus a small
`.mangadex.json` sidecar in each series folder so the library knows what's on disk.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import Counter, OrderedDict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import api
from .cbz import CbzWriter, comic_info, safe_name

Chapter = Dict[str, Any]
META_FILE = ".mangadex.json"
COVER_FILE = ".cover.jpg"
_meta_lock = threading.Lock()


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------- chapter helpers

def parse_ranges(spec: str) -> List[Tuple[float, float]]:
    """'1-10,12,20-' -> [(1,10), (12,12), (20,inf)]"""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.append((float(lo) if lo.strip() else -math.inf,
                        float(hi) if hi.strip() else math.inf))
        else:
            out.append((float(part), float(part)))
    return out


def chapter_num(c: Chapter) -> Optional[float]:
    try:
        return float(c["attributes"].get("chapter"))
    except (TypeError, ValueError):
        return None


def chapter_label(c: Chapter) -> str:
    """'7' -> 'Ch.007', '10.5' -> 'Ch.010.5', None -> 'Oneshot'. Zero-padded so files sort."""
    raw = c["attributes"].get("chapter")
    if not raw:
        return "Oneshot"
    whole, dot, frac = raw.partition(".")
    if whole.isdigit():
        return f"Ch.{whole.zfill(3)}{dot}{frac}"
    return f"Ch.{raw}"


def volume_label(vol: str) -> str:
    whole, dot, frac = vol.partition(".")
    return f"Vol.{whole.zfill(2)}{dot}{frac}" if whole.isdigit() else f"Vol.{vol}"


def sort_key(c: Chapter):
    n = chapter_num(c)
    return (n is None, n if n is not None else 0, c["attributes"].get("publishAt") or "")


def group_counts(chapters: List[Chapter]) -> Counter:
    counts: Counter = Counter()
    for c in chapters:
        for g in api.group_names(c):
            counts[g] += 1
    return counts


def choose_versions(chapters: List[Chapter], prefer_group: Optional[str] = None,
                    all_versions: bool = False) -> List[Chapter]:
    """Several groups often translate the same chapter. Keep one per chapter number:
    the preferred-group match if given, else whichever group did the most chapters
    overall (so the translation stays consistent across the series)."""
    chapters = sorted(chapters, key=sort_key)
    if all_versions:
        return chapters
    counts = group_counts(chapters)
    by_num: "OrderedDict[str, List[Chapter]]" = OrderedDict()
    for c in chapters:
        key = c["attributes"].get("chapter") or f"id:{c['id']}"  # oneshots are each unique
        by_num.setdefault(key, []).append(c)

    def score(c: Chapter):
        groups = api.group_names(c)
        return (max((counts[g] for g in groups), default=0), c["attributes"].get("pages", 0))

    picked = []
    for cands in by_num.values():
        if prefer_group:
            pg = prefer_group.lower()
            matching = [c for c in cands if any(pg in g.lower() for g in api.group_names(c))]
            cands = matching or cands
        picked.append(max(cands, key=score))
    return picked


def filter_ranges(chapters: List[Chapter], spec: str) -> List[Chapter]:
    ranges = parse_ranges(spec)
    return [c for c in chapters if chapter_num(c) is not None
            and any(lo <= chapter_num(c) <= hi for lo, hi in ranges)]  # type: ignore[operator]


# ---------------------------------------------------------------- series

class Series:
    def __init__(self, manga: Dict[str, Any], lang: str = "en"):
        a = manga["attributes"]
        self.manga = manga
        self.id = manga["id"]
        self.title = api.pick_title(a, lang)
        self.summary = api.pick_text(a.get("description"), lang)
        self.year = a.get("year")
        self.cover_url = api.cover_url(manga, 512)

        def names(t: str) -> str:
            return ", ".join(r["attributes"]["name"]
                             for r in api.related(manga, t) if r.get("attributes"))
        self.writer = names("author")
        self.artist = names("artist")

    def folder(self, out_root: str) -> str:
        return os.path.join(os.path.expanduser(out_root), safe_name(self.title))


# ---------------------------------------------------------------- planning output files

@dataclass
class Job:
    name: str            # file name without extension
    path: str            # full .cbz path
    chapters: List[Chapter]
    volume: Optional[str] = None   # set for volume bundles
    pages: int = field(default=0)  # expected page count
    cover_url: Optional[str] = None  # volume cover, written as the first page

    @property
    def exists(self) -> bool:
        return os.path.exists(self.path)


def plan_jobs(series: Series, chapters: List[Chapter], out_root: str, bundle: str = "chapter",
              full: Optional[List[Chapter]] = None, include_loose: bool = True,
              covers: Optional[Dict[str, str]] = None) -> List[Job]:
    """Turn a chapter selection into output files. `full` is the unfiltered (deduped) chapter
    list, used to notice when only part of a volume was requested. In volume mode, chapters that
    aren't in a volume yet are skipped unless `include_loose`. `covers` maps volume -> cover URL."""
    out_dir = series.folder(out_root)
    used: set = set()

    def unique(name: str, c: Optional[Chapter] = None) -> str:
        if name in used and c is not None:
            tag = (api.group_names(c) or [c["id"][:8]])[0]
            name = f"{name} [{safe_name(tag, 40)}]"
            if name in used:
                name = f"{name} {c['id'][:8]}"
        used.add(name)
        return name

    def job(name: str, chs: List[Chapter], vol: Optional[str] = None) -> Job:
        return Job(name, os.path.join(out_dir, safe_name(name, 200) + ".cbz"), chs, vol,
                   sum(c["attributes"].get("pages", 0) for c in chs))

    jobs: List[Job] = []
    if bundle == "volume":
        vols: "OrderedDict[str, List[Chapter]]" = OrderedDict()
        loose: List[Chapter] = []
        for c in chapters:
            v = c["attributes"].get("volume")
            (vols.setdefault(v, []) if v else loose).append(c)

        def vkey(v: str):
            try:
                return (0, float(v))
            except ValueError:
                return (1, 0.0)
        vol_size = Counter(c["attributes"].get("volume") for c in (full or chapters))
        for v in sorted(vols, key=vkey):
            name = f"{series.title} - {volume_label(v)}"
            if len(vols[v]) < vol_size[v]:  # only some of this volume's chapters were requested
                name += f" (partial {chapter_label(vols[v][0])}-{chapter_label(vols[v][-1])})"
            j = job(unique(name), vols[v], v)
            j.cover_url = (covers or {}).get(api.vol_key(v))
            jobs.append(j)
        for c in (loose if include_loose else []):
            jobs.append(job(unique(f"{series.title} - {chapter_label(c)}", c), [c]))
    else:
        for c in chapters:
            jobs.append(job(unique(f"{series.title} - {chapter_label(c)}", c), [c]))
    return jobs


# ---------------------------------------------------------------- downloading

PageCallback = Callable[[Chapter, int, int, int, str, bytes], None]
# on_page(chapter, pages_done, pages_total, page_index, extension, data)


def fetch_image(url: str) -> bytes:
    try:
        return api.fetch(url, retries=2, timeout=60)
    except api.ApiError:
        return api.fetch(api.fallback_url(url), retries=3, timeout=60)


def download_chapter_pages(c: Chapter, *, data_saver: bool = False, workers: int = 4,
                           on_page: Optional[PageCallback] = None,
                           cancel: Optional[threading.Event] = None) -> List[Tuple[str, bytes]]:
    """Returns [(extension, image bytes)] in reading order."""
    urls = api.get_page_urls(c["id"], data_saver)
    total = len(urls)
    results: List[Optional[bytes]] = [None] * total
    done = 0
    ex = ThreadPoolExecutor(max_workers=workers)
    try:
        pending = {ex.submit(fetch_image, u): i for i, u in enumerate(urls)}
        while pending:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            finished, _ = wait(list(pending), timeout=0.5, return_when=FIRST_COMPLETED)
            for fut in finished:
                i = pending.pop(fut)
                results[i] = fut.result()
                done += 1
                if on_page:
                    on_page(c, done, total, i, os.path.splitext(urls[i])[1] or ".jpg", results[i])  # type: ignore[arg-type]
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    exts = [os.path.splitext(u)[1] or ".jpg" for u in urls]
    return list(zip(exts, results))  # type: ignore[arg-type]


def run_job(job: Job, series: Series, *, lang: str = "en", data_saver: bool = False,
            workers: int = 4, on_page: Optional[PageCallback] = None,
            cancel: Optional[threading.Event] = None, out_root: Optional[str] = None) -> int:
    """Download every chapter in `job` and write its .cbz. Returns pages written."""
    count = 0
    groups = sorted({g for c in job.chapters for g in api.group_names(c)})
    with CbzWriter(job.path) as w:
        single = job.volume is None
        if job.cover_url:
            try:
                ext = os.path.splitext(job.cover_url)[1] or ".jpg"
                w.add(f"000{ext}", fetch_image(job.cover_url))  # sorts before 001-001
                count += 1
            except Exception:
                pass  # a missing cover shouldn't sink the volume
        for ci, c in enumerate(job.chapters, 1):
            pages = download_chapter_pages(c, data_saver=data_saver, workers=workers,
                                           on_page=on_page, cancel=cancel)
            for pi, (ext, data) in enumerate(pages, 1):
                w.add(f"{pi:03d}{ext}" if single else f"{ci:03d}-{pi:03d}{ext}", data)
                count += 1
        if single:
            c = job.chapters[0]
            a = c["attributes"]
            info = comic_info(
                series=series.title, number=a.get("chapter") or "1", volume=a.get("volume"),
                title=a.get("title") or "", summary=series.summary, writer=series.writer,
                penciller=series.artist, translator=", ".join(groups),
                language=a.get("translatedLanguage") or lang, page_count=count,
                web=f"https://mangadex.org/chapter/{c['id']}", year=series.year)
        else:
            nums = [c["attributes"].get("chapter") for c in job.chapters if c["attributes"].get("chapter")]
            info = comic_info(
                series=series.title, number=job.volume, volume=job.volume,
                title=f"Chapters {nums[0]}–{nums[-1]}" if len(nums) > 1 else "",
                summary=series.summary, writer=series.writer, penciller=series.artist,
                translator=", ".join(groups), language=lang, page_count=count,
                web=f"https://mangadex.org/title/{series.id}", year=series.year)
        w.add_text("ComicInfo.xml", info)
    record_download(series, job, count)
    return count


# ---------------------------------------------------------------- library sidecar

def read_meta(folder: str) -> Dict[str, Any]:
    try:
        with open(os.path.join(folder, META_FILE), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def record_download(series: Series, job: Job, pages: int) -> None:
    folder = os.path.dirname(job.path)
    with _meta_lock:
        meta = read_meta(folder)
        meta.update({"manga_id": series.id, "title": series.title,
                     "writer": series.writer, "updated": time.time()})
        files = meta.setdefault("files", {})
        files[os.path.basename(job.path)] = {
            "volume": job.volume, "pages": pages, "added": time.time(),
            "chapters": [{"id": c["id"], "chapter": c["attributes"].get("chapter"),
                          "volume": c["attributes"].get("volume"),
                          "lang": c["attributes"].get("translatedLanguage"),
                          "groups": api.group_names(c)} for c in job.chapters],
        }
        tmp = os.path.join(folder, META_FILE + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        os.replace(tmp, os.path.join(folder, META_FILE))
    cover = os.path.join(folder, COVER_FILE)
    if series.cover_url and not os.path.exists(cover):
        try:
            data = api.fetch(series.cover_url, retries=2)
            with open(cover, "wb") as f:
                f.write(data)
        except Exception:
            pass


def downloaded_volumes(folder: str) -> set:
    """Volumes that have a complete (non-partial) .cbz on disk."""
    meta = read_meta(folder)
    out = set()
    for fn, info in (meta.get("files") or {}).items():
        if info.get("volume") and "(partial" not in fn and os.path.exists(os.path.join(folder, fn)):
            out.add(api.vol_key(info["volume"]))
    return out


def volume_gaps(chapters: List[Chapter], next_first: Optional[float] = None) -> List[int]:
    """Whole chapter numbers missing from a volume: holes inside its range, plus any before the
    next volume starts (vol 2 = ch 6-7 but vol 3 starts at 11 -> [8, 9, 10])."""
    nums = sorted({int(n) for n in (chapter_num(c) for c in chapters) if n is not None})
    if not nums:
        return []
    end = nums[-1]
    if next_first is not None and int(next_first) - 1 > end:
        end = int(next_first) - 1
    if end - nums[0] > 2000:
        return []
    have = set(nums)
    return [n for n in range(nums[0], end + 1) if n not in have]


def downloaded_chapters(folder: str) -> Dict[str, Dict[str, set]]:
    """{'ids': {...}, 'numbers': {(lang, chapter), ...}} for files that still exist."""
    meta = read_meta(folder)
    ids, nums = set(), set()
    for fn, info in (meta.get("files") or {}).items():
        if not os.path.exists(os.path.join(folder, fn)):
            continue
        for c in info.get("chapters", []):
            ids.add(c["id"])
            if c.get("chapter"):
                nums.add((c.get("lang"), c["chapter"]))
    return {"ids": ids, "numbers": nums}
