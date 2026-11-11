"""Spot scanlation credit / recruitment / "join our Discord" pages.

How it decides (tuned on real chapters, see README):

* Every page is fingerprinted (perceptual hash, pixel size, colour).
* "Ad-like": nearly identical to a page in *another* chapter (groups reuse one template and only
  change the chapter number / names), or matching a page you removed before (learned blocklist).
* "Foreign": a different size from the chapter's usual page, or colour in a black-and-white
  chapter. Wide double-page spreads don't count.
* From each end of a chapter we walk inward over the run of ad-like / foreign pages — groups put
  whole blocks there (one series had six promo pages per chapter). Ad-like pages in that run are
  removed; foreign-only ones are "maybe" (shown in review, never removed on their own).
  The walk stops at the first normal page, or at a near-blank page.
* Inside a chapter: learned pages are removed; pages repeated across chapters are removed if
  they're also foreign, otherwise "maybe".
* Near-blank pages (logo pages, interludes) are always kept: they're part of the real book.

Needs Pillow; without it everything is kept and `HAS_PIL` is False.
"""
from __future__ import annotations

import io
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

try:
    from PIL import Image
    HAS_PIL = True
    _RESAMPLE = getattr(Image, "Resampling", Image).BILINEAR
except ImportError:  # pragma: no cover - optional dependency
    HAS_PIL = False

HEAD, TAIL = 2, 3          # pages always shown for context in the review
MAX_RUN = 14               # longest ad block we'll walk into from either end of a chapter
REPEAT_DIST = 40           # max differing bits (of 256) to call two pages "the same template"
BLOCK_DIST = 40            # same, for matching the learned blocklist
BLANK_INK = 0.05           # pages with less ink coverage than this are never touched
SIZE_TOL = 0.015           # 1.5% size difference from the chapter's usual page = "odd size"
COLOUR = 0.03              # share of clearly coloured pixels that makes a page "in colour"
BLOCKLIST_PATH = os.path.expanduser("~/.config/mangadex-dl/blocklist.json")


@dataclass
class Fingerprint:
    hash: int
    blank: bool
    w: int
    h: int
    colour: float = 0.0


@dataclass
class Page:
    chapter_id: str
    index: int
    total: int
    filename: str
    fp: Optional[Fingerprint]


def fingerprint(data: bytes) -> Optional[Fingerprint]:
    if not HAS_PIL:
        return None
    try:
        im = Image.open(io.BytesIO(data))
        w, h = im.size
        g = im.convert("L")
        small = g.copy()
        small.thumbnail((96, 96))
        px = list(small.getdata())
        med = sorted(px)[len(px) // 2]
        ink = sum(1 for p in px if abs(p - med) > 48) / len(px)
        hsv = im.convert("RGB")
        hsv.thumbnail((96, 96))
        hv = list(hsv.convert("HSV").getdata())
        colour = sum(1 for p in hv if p[1] > 70 and 40 < p[2] < 245) / len(hv)
        d = list(g.resize((17, 16), _RESAMPLE).getdata())
        bits = 0
        for y in range(16):
            row = y * 17
            for x in range(16):
                bits = (bits << 1) | (d[row + x] > d[row + x + 1])
        return Fingerprint(bits, ink < BLANK_INK, w, h, round(colour, 3))
    except Exception:
        return None


def image_size(data: bytes) -> Optional[Tuple[int, int]]:
    if not HAS_PIL:
        return None
    try:
        return Image.open(io.BytesIO(data)).size  # header only, cheap
    except Exception:
        return None


def dist(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def edge_indexes(n: int) -> List[int]:
    return sorted(set(range(min(HEAD, n))) | set(range(max(0, n - TAIL), n)))


# ---------------------------------------------------------------- learned blocklist

class Blocklist:
    """Fingerprints of pages the user removed. Shared across every series, since groups reuse
    their credit templates everywhere."""

    def __init__(self, path: str = BLOCKLIST_PATH):
        self.path = path
        self.lock = threading.Lock()
        self.entries: List[Dict] = []
        try:
            with open(path, encoding="utf-8") as f:
                self.entries = json.load(f).get("pages", [])
        except (OSError, ValueError):
            pass
        self._ints = [int(e["h"], 16) for e in self.entries]

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"pages": self.entries}, f, indent=1)
        os.replace(tmp, self.path)

    def __len__(self) -> int:
        return len(self.entries)

    def match(self, fp: Optional[Fingerprint]) -> Optional[Dict]:
        if fp is None or fp.blank:
            return None
        for e, h in zip(self.entries, self._ints):
            if dist(fp.hash, h) <= BLOCK_DIST:
                return e
        return None

    def add(self, fp: Fingerprint, group: str = "", series: str = "") -> bool:
        with self.lock:
            if fp.blank or self.match(fp):
                return False
            self.entries.append({"h": f"{fp.hash:064x}", "group": group, "series": series,
                                 "added": int(time.time())})
            self._ints.append(fp.hash)
            self._save()
            return True

    def forget(self, fp: Fingerprint) -> int:
        """Drop entries matching a page the user decided to keep."""
        with self.lock:
            keep = [(e, h) for e, h in zip(self.entries, self._ints) if dist(fp.hash, h) > BLOCK_DIST]
            dropped = len(self.entries) - len(keep)
            if dropped:
                self.entries = [e for e, _ in keep]
                self._ints = [h for _, h in keep]
                self._save()
            return dropped

    def clear(self) -> None:
        with self.lock:
            self.entries, self._ints = [], []
            self._save()


# ---------------------------------------------------------------- the decision

Verdict = Tuple[str, str]  # ("ad" | "maybe" | "keep", reason)


def _usual_size(ps: List[Page]) -> Optional[Tuple[int, int]]:
    """The chapter's normal page size: the most common size, give or take 1%."""
    sizes = [(p.fp.w, p.fp.h) for p in ps if p.fp and not p.fp.blank and p.fp.w <= p.fp.h * 1.15]
    if not sizes:
        return None
    best, best_n = None, 0
    for w, h in sizes:
        n = sum(1 for x, y in sizes if abs(x - w) <= w * SIZE_TOL and abs(y - h) <= h * SIZE_TOL)
        if n > best_n:
            best, best_n = (w, h), n
    return best


def analyze(pages: Iterable[Page], blocklist: Optional[Blocklist] = None,
            ref_sizes: Optional[Dict[str, Tuple[int, int]]] = None) -> Dict[Tuple[str, int], Verdict]:
    """Verdicts for every page, keyed by (chapter_id, index). Pages not mentioned are kept."""
    pages = list(pages)
    by_ch: Dict[str, List[Page]] = {}
    for p in pages:
        by_ch.setdefault(p.chapter_id, []).append(p)
    for ps in by_ch.values():
        ps.sort(key=lambda p: p.index)
    solid = [p for p in pages if p.fp and not p.fp.blank]

    twins: Dict[Tuple[str, int], int] = {}  # how many *other* chapters a page appears in
    for k, p in enumerate(solid):
        for q in solid[k + 1:]:
            if q.chapter_id != p.chapter_id and dist(p.fp.hash, q.fp.hash) <= REPEAT_DIST:  # type: ignore[union-attr]
                twins.setdefault((p.chapter_id, p.index), set()).add(q.chapter_id)  # type: ignore[arg-type]
                twins.setdefault((q.chapter_id, q.index), set()).add(p.chapter_id)  # type: ignore[arg-type]

    out: Dict[Tuple[str, int], Verdict] = {}
    for cid, ps in by_ch.items():
        usual = _usual_size(ps) if len(ps) >= 4 else None
        usual = usual or (ref_sizes or {}).get(cid)
        greyscale = sum(1 for p in ps if p.fp and p.fp.colour > COLOUR) < max(2, len(ps) * 0.3)

        def adlike(p: Page) -> Optional[str]:
            if blocklist is not None and blocklist.match(p.fp):
                return "you removed this before"
            t = twins.get((p.chapter_id, p.index))
            return f"repeats in {len(t) + 1} chapters" if t else None

        def foreign(p: Page) -> Optional[str]:
            fp = p.fp
            if fp is None or fp.w > fp.h * 1.15:  # spreads are normal
                return None
            if usual and (abs(fp.w - usual[0]) > usual[0] * SIZE_TOL or abs(fp.h - usual[1]) > usual[1] * SIZE_TOL):
                return "odd size for this chapter"
            if greyscale and fp.colour > COLOUR:
                return "colour page in a b&w chapter"
            return None

        in_run = set()
        for seq in (ps[:MAX_RUN], list(reversed(ps))[:MAX_RUN]):
            run: List[Tuple[int, Verdict]] = []
            for p in seq:
                if p.fp is None:
                    break
                if p.fp.blank:
                    out[(cid, p.index)] = ("keep", "blank page")
                    break
                why_ad, why_odd = adlike(p), foreign(p)
                if why_ad:
                    run.append((p.index, ("ad", why_ad)))
                elif why_odd:
                    run.append((p.index, ("maybe", why_odd)))
                else:
                    break
            touches_ad = any(v[0] == "ad" for _, v in run)
            for idx, v in run:
                # A lone colour page at a chapter edge is usually the chapter's colour opener;
                # only flag colour when it's part of a block that contains an actual ad.
                if v[0] == "maybe" and v[1].startswith("colour") and not touches_ad:
                    continue
                out[(cid, idx)] = v
                in_run.add(idx)

        for p in ps:
            if p.index in in_run or p.fp is None or p.fp.blank:
                continue
            why_ad = adlike(p)
            if not why_ad:
                continue
            if why_ad.startswith("you removed") or foreign(p):
                out[(cid, p.index)] = ("ad", why_ad if why_ad.startswith("you") else f"inserted page, {why_ad}")
            else:
                out[(cid, p.index)] = ("maybe", why_ad)
    return out


def median_size(sizes: Iterable[Optional[Tuple[int, int]]]) -> Optional[Tuple[int, int]]:
    s = [x for x in sizes if x]
    if not s:
        return None
    ws, hs = sorted(x[0] for x in s), sorted(x[1] for x in s)
    return ws[len(ws) // 2], hs[len(hs) // 2]
