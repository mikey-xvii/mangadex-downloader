"""Writing .cbz archives (a zip of images, plus ComicInfo.xml metadata)."""
from __future__ import annotations

import os
import re
import zipfile
from typing import Optional
from xml.sax.saxutils import escape


def safe_name(s: str, max_len: int = 120) -> str:
    s = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", s)
    s = re.sub(r"\s+", " ", s).strip().rstrip(".")
    return s[:max_len].strip() or "untitled"


def comic_info(*, series: str, number: Optional[str] = None, volume: Optional[str] = None,
               title: str = "", summary: str = "", writer: str = "", penciller: str = "",
               translator: str = "", language: str = "", page_count: int = 0,
               web: str = "", year: Optional[int] = None, manga: bool = True) -> str:
    """ComicInfo.xml (Anansi schema v2) — read by Komga, Kavita, Panels, Mihon, Chunky, etc."""
    fields = [
        ("Title", title),
        ("Series", series),
        ("Number", number),
        ("Volume", volume),
        ("Summary", summary),
        ("Year", year),
        ("Writer", writer),
        ("Penciller", penciller),
        ("Translator", translator),
        ("LanguageISO", language),
        ("PageCount", page_count or None),
        ("Web", web),
        ("Manga", "YesAndRightToLeft" if manga else None),
    ]
    lines = ['<?xml version="1.0" encoding="utf-8"?>',
             '<ComicInfo xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
             'xmlns:xsd="http://www.w3.org/2001/XMLSchema">']
    for tag, val in fields:
        if val not in (None, ""):
            lines.append(f"  <{tag}>{escape(str(val))}</{tag}>")
    lines.append("</ComicInfo>")
    return "\n".join(lines) + "\n"


class CbzWriter:
    """Writes to `<path>.part` and renames on success, so a crash or Ctrl-C
    never leaves a half-written .cbz that would be skipped on the next run."""

    def __init__(self, path: str):
        self.path = path
        self.tmp = path + ".part"
        self.zf: Optional[zipfile.ZipFile] = None

    def __enter__(self) -> "CbzWriter":
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        # Images are already compressed; storing them is faster and just as small.
        self.zf = zipfile.ZipFile(self.tmp, "w", compression=zipfile.ZIP_STORED)
        return self

    def add(self, name: str, data: bytes) -> None:
        assert self.zf
        self.zf.writestr(name, data)

    def add_text(self, name: str, text: str) -> None:
        assert self.zf
        self.zf.writestr(name, text.encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)

    def __exit__(self, exc_type, exc, tb) -> None:
        assert self.zf
        self.zf.close()
        if exc_type is None:
            os.replace(self.tmp, self.path)
        else:
            try:
                os.remove(self.tmp)
            except OSError:
                pass
