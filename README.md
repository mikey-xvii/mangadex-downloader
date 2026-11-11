# Tankōbon (mangadex-dl)

Paste a [MangaDex](https://mangadex.org) link and get **one `.cbz` per volume**. Each file has
that volume's own cover as its first page plus `ComicInfo.xml` metadata, ready to AirDrop to
your phone's comic reader (Panels, Chunky, Komik…).

Python 3.8+ standard library. Pillow is optional and turns on ad-page filtering.

## The web app

```bash
python3 -m mangadex_dl serve
```

That opens `http://localhost:8787`. From there:

- **Find**: paste a title or chapter link (or press ⌘V anywhere on the page, or drag a link in),
  or type a name to search.
- **Pick volumes**: every volume is shown with its real cover. Click to select, shift-click for
  a run, or drag across the chapter strip (one bar per chapter, grouped by volume).
  - Volumes already on your shelf are marked.
  - Volumes with holes in their chapter list show a ⚠ "missing ch. …" warning before you bind.
- **Review pages** (optional): open the proofing room before binding. It reads every page,
  stamps the credit/recruitment/"join our Discord" pages it
  finds with 除, and lets you flip anything it got wrong. See *Ad & credit pages* below.
- **Bind**: watch the press. Pages fly in live, the volume cover fills with ink as it downloads,
  and you get speed and an ETA.
- **Shelf**: everything you've bound, as 3D books. Read any volume in the built-in reader
  (manga right-to-left, comic left-to-right, or vertical scroll), or hit **Show in Finder** to
  AirDrop it.
- **Connect MangaDex** (optional): see new chapters from your follows, your reading statuses
  and your custom lists.

Options: `serve --port 8787 --out ./downloads --no-open`. It only listens on `127.0.0.1`.

### Ad & credit pages

Scanlation groups often add credits, recruitment ("join our Discord") or promo pages to
chapters, sometimes a whole block of them. They're removed automatically when you bind (the
**Strip ads** switch; `--keep-ads` on the command line turns it off). Every page is
fingerprinted (perceptual hash, pixel size, colour). Then:

- **Ad-like pages are removed.** A page is ad-like if it's nearly identical to a page in another
  chapter (groups reuse one template and only change the chapter number), or if you removed it
  before.
- **Whole blocks at the start or end are caught.** From each end of a chapter it walks inward
  while pages are ad-like or *foreign* (a different size from the chapter's usual page, or colour
  in a black-and-white chapter), and stops at the first normal page. One series had a six-page
  promo block at the end of every chapter. Inside a volume those blocks sit in the middle of the
  book, so the walk matters there too.
- **Foreign alone is never enough.** A page that's only foreign is marked "worth a look" in the
  review, and never removed on its own. A lone colour chapter opener isn't flagged at all.
- **Inside a chapter,** learned pages are removed, and repeated pages are removed if they're also
  foreign.
- **Near-blank pages are always kept.** Logo pages and interludes are part of the real book.
- **Learned pages are kept in** `~/.config/mangadex-dl/blocklist.json` and recognised in any
  series. Keep a page in the review and it's forgotten again.

**Review pages** shows all of this before you bind. It reads every page and shows only the
flagged ones in place, with a count of the story pages between them. The bind afterwards reuses
those pages, so it takes seconds. Tested on two series: one with a 7-chapter volume carrying
36 promo / credit pages (including six-page blocks at chapter ends), and The Girl From the
Other Side Vol. 1–2 (7 credits pages). All were removed and no story pages were lost. This needs Pillow (`pip install pillow`;
Anaconda already has it). Without Pillow the filter turns itself off.

### Chapters that aren't in a volume yet

Chapters that MangaDex hasn't tagged with a volume number (usually the newest ones) are
listed under **Waiting for a volume** and are not bound. Once MangaDex groups them into a
volume, that volume shows up ready to bind.

### Logging in

Logging in is only needed for account features; downloading never needs it. MangaDex uses
*personal API clients*:

1. Open <https://mangadex.org/settings> → **API Clients** and create a personal client.
2. Wait until it's **approved** (sometimes instant, sometimes a staff review), then click
   **Get Secret**.
3. In Tankōbon, click **Connect MangaDex** and enter your username, password, client ID and
   secret.

Your password goes to `auth.mangadex.org` once and is never stored. Only the client ID/secret
and a refresh token are kept, in `~/.config/mangadex-dl/auth.json` (mode 600).

## The command line

```bash
# list what's available
python3 -m mangadex_dl "the girl from the other side" --list

# every volume (one .cbz each, with covers) into ./downloads/<Series>/
python3 -m mangadex_dl https://mangadex.org/title/<id>

# just some volumes
python3 -m mangadex_dl https://mangadex.org/title/<id> --volumes 1-3
```

| flag | what it does |
|---|---|
| `-v, --volumes 1-3,5` | volume ranges (default: all) |
| `-l, --lang en,es-la` | translation language(s), default `en` |
| `-g, --group NAME` | prefer a scanlation group (substring match) |
| `--loose` | also bind chapters that aren't in a volume yet, one file each |
| `--keep-ads` | don't remove scanlator credit/recruitment pages |
| `-b chapter` | one file per chapter instead of per volume |
| `-c, --chapters 1-10` | filter by chapter number |
| `-o, --out DIR` | output folder, default `./downloads` |
| `--data-saver` | smaller compressed images |
| `-y, --yes` / `-f, --force` / `-w N` | first search hit / re-download / parallel image downloads |

A chapter URL (`https://mangadex.org/chapter/<id>`) always downloads just that chapter.

## How it behaves

- **Resumable.** Files are written as `.cbz.part` and renamed when complete. Volumes already on
  disk are skipped, so re-running only fetches what's new.
- **One translation per chapter.** When several groups translated the same chapter, it uses
  the group that did the most chapters of the series, so a volume reads consistently. You can
  override this with **Group** in the app or `--group` on the command line.
- **Volume covers.** The cover in your reading language is preferred, then the original
  Japanese one. It's stored as `000.jpg` so readers use it as the thumbnail.
- **Licensed series.** Many popular titles (One-Punch Man, Dandadan…) only link to official
  sites like MangaPlus. MangaDex has no pages for them, and the app tells you so.
- **Rate limits.** It stays under MangaDex's limits (≈4 req/s to the API, 40/min for image-server
  lookups), retries on 429/5xx, and falls back to `uploads.mangadex.org` if an image node fails.

## Getting files onto your phone

On the Shelf, hit the folder icon to reveal a volume in Finder, then AirDrop it to your iPhone
and open it in your reader.

## Layout

```
mangadex_dl/
  api.py      MangaDex API client (rate limiting, retries, covers)
  engine.py   chapter selection, volume planning, downloading, .cbz writing
  adfilter.py credit/ad page detection + learned blocklist
  cbz.py      zip + ComicInfo.xml
  auth.py     personal-client login and token refresh
  server.py   local web app: JSON API + live progress over Server-Sent Events
  cli.py      command line
  web/        index.html, style.css, app.js (no build step)
```
