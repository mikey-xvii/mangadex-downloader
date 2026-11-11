"""Minimal MangaDex API v5 client (stdlib only).

Docs: https://api.mangadex.org/docs/
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional

API = "https://api.mangadex.org"
UPLOADS = "https://uploads.mangadex.org"
USER_AGENT = "mangadex-cbz/0.1"

ALL_RATINGS = ["safe", "suggestive", "erotica", "pornographic"]

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)


class ApiError(Exception):
    pass


class RateLimiter:
    """Spaces out calls so we never exceed `per_second` across threads."""

    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second
        self.lock = threading.Lock()
        self.next_at = 0.0

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            if self.next_at > now:
                time.sleep(self.next_at - now)
                now = self.next_at
            self.next_at = now + self.interval


# MangaDex allows ~5 req/s globally and 40 req/min on /at-home/server.
_api_limiter = RateLimiter(4)
_athome_limiter = RateLimiter(40 / 60)


def _retry_delay(err: urllib.error.HTTPError, attempt: int) -> float:
    hdr = err.headers.get("X-RateLimit-Retry-After") or err.headers.get("Retry-After")
    if hdr:
        try:
            val = float(hdr)
            # X-RateLimit-Retry-After is a unix timestamp; Retry-After is seconds.
            return max(1.0, val - time.time()) if val > 1e9 else max(1.0, val)
        except ValueError:
            pass
    return 2.0 ** attempt


def fetch(url: str, *, limiter: Optional[RateLimiter] = None, retries: int = 4,
          timeout: float = 30, headers: Optional[Dict[str, str]] = None,
          data: Optional[bytes] = None) -> bytes:
    last: Exception = ApiError(f"failed to fetch {url}")
    for attempt in range(retries + 1):
        if limiter:
            limiter.wait()
        req = urllib.request.Request(url, data=data,
                                     headers={"User-Agent": USER_AGENT, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429 or e.code >= 500:
                if attempt < retries:
                    time.sleep(_retry_delay(e, attempt))
                    continue
            # 4xx other than 429: surface MangaDex's error detail if present.
            try:
                body = json.loads(e.read().decode())
                detail = "; ".join(x.get("detail") or x.get("title", "") for x in body.get("errors", []))
            except Exception:
                detail = ""
            raise ApiError(f"HTTP {e.code} for {url}" + (f": {detail}" if detail else "")) from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = e
            if attempt < retries:
                time.sleep(2.0 ** attempt)
                continue
    raise ApiError(f"giving up on {url}: {last}")


def get_json(path: str, params: Optional[Dict[str, Any]] = None, *,
             limiter: RateLimiter = _api_limiter, token: Optional[str] = None) -> Dict[str, Any]:
    """GET an api.mangadex.org endpoint. `token` (an OAuth access token) is only ever
    sent here — never to image hosts, per MangaDex's rules."""
    url = API + path
    if params:
        url += "?" + urllib.parse.urlencode(params, doseq=True)
    headers = {"Authorization": f"Bearer {token}"} if token else None
    data = json.loads(fetch(url, limiter=limiter, headers=headers).decode())
    if data.get("result") not in ("ok", None):
        raise ApiError(f"API error for {path}: {data.get('errors')}")
    return data


# ---------------------------------------------------------------- helpers

def parse_target(s: str) -> Optional[Dict[str, str]]:
    """Recognise a MangaDex URL or bare UUID. Returns {'kind', 'id'} or None."""
    m = UUID_RE.search(s)
    if not m:
        return None
    kind = "chapter" if "/chapter/" in s else "manga"
    return {"kind": kind, "id": m.group(0).lower()}


def pick_title(attrs: Dict[str, Any], lang: str = "en") -> str:
    titles = attrs.get("title") or {}
    if lang in titles:
        return titles[lang]
    for alt in attrs.get("altTitles") or []:
        if lang in alt:
            return alt[lang]
    if "en" in titles:
        return titles["en"]
    return next(iter(titles.values()), "Untitled")


def pick_text(d: Optional[Dict[str, str]], lang: str = "en") -> str:
    if not d:
        return ""
    return d.get(lang) or d.get("en") or next(iter(d.values()), "")


def related(entity: Dict[str, Any], rel_type: str) -> List[Dict[str, Any]]:
    return [r for r in entity.get("relationships", []) if r.get("type") == rel_type]


def group_names(chapter: Dict[str, Any]) -> List[str]:
    names = []
    for g in related(chapter, "scanlation_group"):
        name = (g.get("attributes") or {}).get("name")
        if name:
            names.append(name)
    return names


# ---------------------------------------------------------------- endpoints

def search_manga(title: str, limit: int = 10) -> List[Dict[str, Any]]:
    return get_json("/manga", {
        "title": title,
        "limit": limit,
        "order[relevance]": "desc",
        "includes[]": ["author", "cover_art"],
    })["data"]


def get_manga_batch(ids: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        out += get_json("/manga", {
            "ids[]": chunk, "limit": len(chunk), "contentRating[]": ALL_RATINGS,
            "includes[]": ["author", "cover_art"],
        })["data"]
    return out


def get_statistics(manga_id: str) -> Dict[str, Any]:
    try:
        return get_json(f"/statistics/manga/{manga_id}")["statistics"].get(manga_id, {})
    except ApiError:
        return {}


def vol_key(v: Optional[str]) -> Optional[str]:
    """Normalise volume labels so '01', '1' and '1.0' match."""
    if v is None:
        return None
    try:
        f = float(v)
        return str(int(f)) if f.is_integer() else str(f)
    except ValueError:
        return v.strip()


def get_volume_covers(manga_id: str, langs: List[str]) -> Dict[str, str]:
    """{volume: original cover URL}. MangaDex keeps one cover per volume (often per locale too);
    prefer the reading language, then the original language, then anything."""
    covers: List[Dict[str, Any]] = []
    offset = 0
    while True:
        d = get_json("/cover", {"manga[]": [manga_id], "limit": 100, "offset": offset,
                                "order[volume]": "asc"})
        covers += d["data"]
        offset += 100
        if offset >= d.get("total", 0):
            break
    rank = {l: i for i, l in enumerate(langs)}
    best: Dict[str, Any] = {}
    for c in covers:
        a = c["attributes"]
        v = vol_key(a.get("volume"))
        if not v or not a.get("fileName"):
            continue
        score = rank.get(a.get("locale"), len(rank))
        if v not in best or score < best[v][0]:
            best[v] = (score, f"{UPLOADS}/covers/{manga_id}/{a['fileName']}")
    return {v: url for v, (_, url) in best.items()}


def cover_url(manga: Dict[str, Any], size: int = 512) -> Optional[str]:
    """size: 256 or 512 thumbnail, or 0 for the original."""
    for r in related(manga, "cover_art"):
        fn = (r.get("attributes") or {}).get("fileName")
        if fn:
            return f"{UPLOADS}/covers/{manga['id']}/{fn}" + (f".{size}.jpg" if size else "")
    return None


def get_manga(manga_id: str) -> Dict[str, Any]:
    return get_json(f"/manga/{manga_id}", {
        "includes[]": ["author", "artist", "cover_art"],
    })["data"]


def get_chapter(chapter_id: str) -> Dict[str, Any]:
    return get_json(f"/chapter/{chapter_id}", {
        "includes[]": ["scanlation_group", "manga"],
    })["data"]


def iter_chapters(manga_id: str, langs: Iterable[str]) -> List[Dict[str, Any]]:
    """All readable chapters of a manga in the given languages."""
    out: List[Dict[str, Any]] = []
    offset, limit = 0, 500
    while True:
        data = get_json(f"/manga/{manga_id}/feed", {
            "translatedLanguage[]": list(langs),
            "contentRating[]": ALL_RATINGS,
            "includes[]": ["scanlation_group"],
            "order[volume]": "asc",
            "order[chapter]": "asc",
            "includeExternalUrl": 0,
            "includeEmptyPages": 0,
            "includeFuturePublishAt": 0,
            "limit": limit,
            "offset": offset,
        })
        out.extend(data["data"])
        offset += limit
        if offset >= data.get("total", 0) or offset >= 10000:
            break
    # Belt and braces: externally hosted chapters (e.g. MangaPlus) have no pages here.
    return [c for c in out
            if not c["attributes"].get("externalUrl") and c["attributes"].get("pages", 0) > 0]


def get_page_urls(chapter_id: str, data_saver: bool = False) -> List[str]:
    """Ask MangaDex@Home for a server and build the image URLs for one chapter."""
    data = get_json(f"/at-home/server/{chapter_id}", limiter=_athome_limiter)
    base = data["baseUrl"]
    ch = data["chapter"]
    quality, files = ("data-saver", ch["dataSaver"]) if data_saver else ("data", ch["data"])
    return [f"{base}/{quality}/{ch['hash']}/{f}" for f in files]


def fallback_url(url: str) -> str:
    """Same image path on MangaDex's own upload server, used if an @Home node fails."""
    m = re.search(r"/(data|data-saver)/[0-9a-f]+/.+$", url)
    return UPLOADS + m.group(0) if m else url
