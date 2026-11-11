"""Command-line entry point: search / pick a manga, choose chapters, write .cbz files.

`mangadex-dl serve` starts the web app instead.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from typing import Any, Dict, List, Optional

from . import api, engine
from .engine import Series, chapter_label

Chapter = Dict[str, Any]


def run_downloads(series: Series, chapters: List[Chapter], args,
                  full: Optional[List[Chapter]] = None) -> int:
    lang = args.lang.split(",")[0]
    covers: Dict[str, str] = {}
    if args.bundle == "volume":
        orig = series.manga["attributes"].get("originalLanguage") or "ja"
        try:
            covers = api.get_volume_covers(series.id, [lang, orig])
        except api.ApiError:
            pass
        loose = [c for c in chapters if not c["attributes"].get("volume")]
        if loose and not args.loose:
            print(f"{len(loose)} chapter(s) aren't in a volume yet, so they'll wait "
                  f"(from {chapter_label(loose[0])}). Use --loose to bind them one per file.")
    jobs = engine.plan_jobs(series, chapters, args.out, args.bundle, full,
                            include_loose=args.loose, covers=covers)
    if not jobs:
        print("Nothing to bind.")
        return 0
    stats: Counter = Counter()
    print(f"Saving to {series.folder(args.out)}")
    for n, job in enumerate(jobs, 1):
        prefix = f"[{n}/{len(jobs)}] {os.path.basename(job.path)}:"
        if job.exists and not args.force:
            print(f"{prefix} already exists, skipping")
            stats["skipped"] += 1
            continue

        def on_page(c, done, total, _i, _ext, _data, prefix=prefix, job=job):
            sub = f" {chapter_label(c)}" if job.volume else ""
            print(f"\r{prefix}{sub} page {done}/{total}", end="", flush=True)
        try:
            count = engine.run_job(job, series, lang=lang, data_saver=args.data_saver,
                                   workers=args.workers, on_page=on_page)
            print(f"\r{prefix} {count} pages ✓" + " " * 20)
            stats["downloaded"] += 1
        except KeyboardInterrupt:
            print("\nInterrupted. Partial file removed; re-run to resume.")
            raise SystemExit(130)
        except Exception as e:  # keep going with the rest of the chapters
            print(f"\r{prefix} FAILED: {e}")
            stats["failed"] += 1

    print(f"\nDone: {stats['downloaded']} downloaded, {stats['skipped']} skipped, "
          f"{stats['failed']} failed.")
    return 1 if stats["failed"] else 0


def choose_manga(query: str, auto_yes: bool) -> Dict[str, Any]:
    results = api.search_manga(query)
    if not results:
        sys.exit(f"No manga found for {query!r}.")
    for i, m in enumerate(results, 1):
        a = m["attributes"]
        authors = ", ".join(r["attributes"]["name"] for r in api.related(m, "author")
                            if r.get("attributes"))
        bits = [str(x) for x in (a.get("year"), a.get("status"), authors) if x]
        print(f"{i:2}. {api.pick_title(a)}" + (f"  ({' · '.join(bits)})" if bits else ""))
    if auto_yes or len(results) == 1:
        return results[0]
    if not sys.stdin.isatty():
        sys.exit("Several matches; pass a MangaDex URL or use -y to take the first.")
    while True:
        choice = input(f"Pick 1-{len(results)} (q to quit): ").strip().lower()
        if choice in ("q", "quit", ""):
            sys.exit(0)
        if choice.isdigit() and 1 <= int(choice) <= len(results):
            return results[int(choice) - 1]


def list_chapters(chapters: List[Chapter]) -> None:
    for c in chapters:
        a = c["attributes"]
        vol = f"Vol.{a['volume']}" if a.get("volume") else ""
        groups = ", ".join(api.group_names(c)) or "no group"
        title = f"  {a['title']}" if a.get("title") else ""
        print(f"{chapter_label(c):<12} {vol:<8} {a.get('pages', 0):>3}p  "
              f"[{groups}] ({a.get('translatedLanguage')}){title}")
    print(f"\n{len(chapters)} chapters")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mangadex-dl",
        description="Download manga from MangaDex as .cbz files.",
        epilog="examples:\n"
               "  mangadex-dl serve                       # open the web app\n"
               "  mangadex-dl 'one punch man' --list\n"
               "  mangadex-dl https://mangadex.org/title/<id> -c 1-10\n"
               "  mangadex-dl https://mangadex.org/title/<id> --volumes 1-3\n"
               "  mangadex-dl https://mangadex.org/chapter/<id>",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("target", nargs="+", help="MangaDex title/chapter URL, UUID, or search words")
    p.add_argument("-l", "--lang", default="en",
                   help="translation language(s), comma separated (default: en)")
    p.add_argument("-v", "--volumes", help="volume ranges, e.g. '1-3,5' (default: all)")
    p.add_argument("-c", "--chapters", help="chapter ranges, e.g. '1-10,12,20-' (default: all)")
    p.add_argument("-g", "--group", help="prefer this scanlation group (substring match)")
    p.add_argument("--all-versions", action="store_true",
                   help="keep every group's version of a chapter instead of picking one")
    p.add_argument("-b", "--bundle", choices=["volume", "chapter"], default="volume",
                   help="one .cbz per volume with its own cover (default), or per chapter")
    p.add_argument("--loose", action="store_true",
                   help="also bind chapters that aren't in a volume yet (one file each)")
    p.add_argument("-o", "--out", default="downloads", help="output folder (default: ./downloads)")
    p.add_argument("--data-saver", action="store_true", help="smaller, compressed images")
    p.add_argument("--list", action="store_true", help="list chapters and exit")
    p.add_argument("-y", "--yes", action="store_true", help="take the first search result")
    p.add_argument("-f", "--force", action="store_true", help="re-download existing files")
    p.add_argument("-w", "--workers", type=int, default=4, help="parallel image downloads (default: 4)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "serve":
        from .server import main as serve_main
        return serve_main(argv[1:])

    args = build_parser().parse_args(argv)
    args.workers = max(1, min(args.workers, 10))
    target = " ".join(args.target)
    langs = [x.strip() for x in args.lang.split(",") if x.strip()]

    try:
        parsed = api.parse_target(target)
        if parsed and parsed["kind"] == "chapter":
            c = api.get_chapter(parsed["id"])
            manga_rel = api.related(c, "manga")
            if not manga_rel:
                sys.exit("Couldn't find the manga this chapter belongs to.")
            series = Series(api.get_manga(manga_rel[0]["id"]), langs[0])
            if c["attributes"].get("externalUrl"):
                sys.exit(f"This chapter is hosted externally ({c['attributes']['externalUrl']}) "
                         "and can't be downloaded from MangaDex.")
            print(f"{series.title} — {chapter_label(c)}")
            chapters = full = [c]
            args.bundle, args.loose = "chapter", True
        else:
            manga = api.get_manga(parsed["id"]) if parsed else choose_manga(target, args.yes)
            if not parsed:
                manga = api.get_manga(manga["id"])  # re-fetch with artist/cover includes
            series = Series(manga, langs[0])
            print(f"\n{series.title}  https://mangadex.org/title/{series.id}")
            all_chs = api.iter_chapters(series.id, langs)
            if not all_chs:
                sys.exit(f"No downloadable chapters in {','.join(langs)}. "
                         "(Some series are only linked to official sites like MangaPlus.)")
            chapters = full = engine.choose_versions(all_chs, args.group, args.all_versions)
            if args.chapters:
                try:
                    chapters = engine.filter_ranges(chapters, args.chapters)
                except ValueError:
                    sys.exit(f"Bad --chapters value: {args.chapters!r}")
                if not chapters:
                    sys.exit("No chapters match that range. Try --list to see what's available.")
            if args.volumes:
                try:
                    ranges = engine.parse_ranges(args.volumes)
                except ValueError:
                    sys.exit(f"Bad --volumes value: {args.volumes!r}")

                def in_vol(c):
                    try:
                        v = float(c["attributes"].get("volume"))
                    except (TypeError, ValueError):
                        return False
                    return any(lo <= v <= hi for lo, hi in ranges)
                chapters = [c for c in chapters if in_vol(c)]
                if not chapters:
                    sys.exit("No chapters in those volumes. Try --list to see what's available.")

        if args.list:
            list_chapters(chapters)
            return 0
        return run_downloads(series, chapters, args, full)
    except api.ApiError as e:
        sys.exit(f"Error: {e}")
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    sys.exit(main())
