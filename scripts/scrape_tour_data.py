#!/usr/bin/env python
"""Scrape Tour de France stage previews from The Inner Ring (inrng.com).

This is the *ingestion* step for switching the workshop's underlying data to
Tour de France data. It discovers every stage-preview post across every
available edition and extracts a clean text description for each, writing them
to ``data/tour_stages.json``. From there, ``dataset.py`` maps them into
``Document`` objects exactly like it does for conference sessions today.

Why discovery (not URL construction)? The stage-preview slugs are *not* uniform
across editions, so you cannot just build the URLs:

    2026 : https://inrng.com/2026/07/tour-de-france-stage-1/
    2025 : https://inrng.com/2025/07/tour-de-france-stage-1-preview-lille/
    2023 : https://inrng.com/2023/07/tour-de-france-stage-1-preview-bilbao/
    2020 : https://inrng.com/2020/08/tour-de-france-stage-1-preview-nice/   (Aug!)

The town suffix is unpredictable and the month shifts (the 2020 Tour ran in
Aug/Sep). So instead we *discover* URLs:

1. Crawl the site's XML sitemap(s) and keep every URL that looks like a
   stage preview (this finds every edition automatically), and
2. additionally harvest stage links from index/guide pages (``/tour/`` and any
   ``--seed-url`` you pass) as a fallback / to catch a just-published stage the
   sitemap hasn't picked up yet.

Content extraction is a small, dependency-free WordPress reader: it isolates the
``.entry-content`` article body and drops the comment thread, share buttons and
"related posts" cruft. Only ``requests`` (already a project dependency) and the
Python standard library are used — swap in BeautifulSoup if you prefer, the
seam is :class:`_TextExtractor`.

Examples::

    python scripts/scrape_tour_data.py                    # every edition it can find
    python scripts/scrape_tour_data.py --years 2024 2025  # just these editions
    python scripts/scrape_tour_data.py --year-min 2020    # 2020 onwards
    python scripts/scrape_tour_data.py --limit 3 -v       # smoke test: 3 stages, verbose

Note: inrng.com serves 403 to obvious bots. The default User-Agent is a real
browser string and requests are rate-limited (``--delay``); please keep it
polite — this is one person's blog.
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

# Make ``import agentic_search`` work when running this file directly (no install).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_search.config import DATA_DIR  # noqa: E402

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

BASE_URL = "https://inrng.com"

# The canonical shape of a stage-preview URL. Captures (year, month, stage).
# Tolerant of an optional year in the slug and any trailing "-preview-<town>".
#   /2026/07/tour-de-france-stage-1/
#   /2023/07/tour-de-france-stage-1-preview-bilbao/
#   /2019/07/tour-de-france-2019-stage-1-preview-brussels/   (year-in-slug form)
STAGE_URL_RE = re.compile(
    r"https?://(?:www\.)?inrng\.com/(\d{4})/(\d{2})/"
    r"tour-de-france-(?:\d{4}-)?stage-(\d+)\b",
    re.IGNORECASE,
)

# Sitemap locations to probe, in order (Yoast/Rank Math first, then WP core).
SITEMAP_PATHS = ["/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap.xml", "/sitemap-index.xml"]

# Index/guide pages harvested for stage links by default (belt and braces).
DEFAULT_SEED_URLS = [f"{BASE_URL}/tour/"]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# CSS class / id substrings that mark the article body in a WordPress theme.
CONTENT_HINTS = (
    "entry-content", "post-content", "article-content", "td-post-content",
    "post-entry", "single-content", "the-content", "entry-body",
)
# Substrings that mark *junk* nested inside the article body (skip their text).
JUNK_HINTS = (
    "sharedaddy", "jp-relatedposts", "sd-block", "share-", "sharing",
    "social", "comment", "respond", "reply", "related", "post-nav",
    "nav-links", "author-box", "author-bio", "entry-meta", "post-meta",
    "widget", "sidebar", "footer", "subscribe", "newsletter", "advert",
    "wpcnt", "screen-reader", "breadcrumb",
)

MIN_CONTENT_CHARS = 200  # below this we retry extraction with looser selectors

DEFAULT_OUT = DATA_DIR / "tour_stages.json"


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class StageRecord:
    """One scraped stage preview."""

    edition: int          # Tour year, e.g. 2024
    stage: int            # stage number, e.g. 1..21
    title: str            # "Tour de France Stage 1 Preview"
    url: str
    date: str             # publish date "YYYY-MM-DD" (best effort, may be "")
    description: str      # cleaned article text — what gets embedded / searched
    word_count: int = 0


# --------------------------------------------------------------------------- #
# HTML -> text (the swappable seam; replace with BeautifulSoup if you prefer)
# --------------------------------------------------------------------------- #

from html.parser import HTMLParser  # noqa: E402

_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "div", "dd", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
    "section", "table", "tr", "ul",
}
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe"}


class _Frame:
    """A single open element on the parser's stack."""

    __slots__ = ("tag", "content", "junk", "skip")

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.content = False  # this frame opened the article body
        self.junk = False     # this frame opened a junk region (comments, share…)
        self.skip = False     # this frame opened a script/style/etc region


class _TextExtractor(HTMLParser):
    """Pull the ``<title>``, key ``<meta>`` tags and article body text out of a
    WordPress page, tolerant of unclosed tags and nested junk.

    The article body is the first element whose class/id matches
    ``content_hints`` (or a tag in ``content_tags``). Text from junk regions
    (comment thread, share widgets, related posts) nested inside it is skipped.
    """

    def __init__(
        self,
        content_hints: tuple[str, ...] = CONTENT_HINTS,
        content_tags: frozenset[str] = frozenset(),
        junk_hints: tuple[str, ...] = JUNK_HINTS,
    ) -> None:
        super().__init__(convert_charrefs=True)
        self._content_hints = content_hints
        self._content_tags = content_tags
        self._junk_hints = junk_hints

        self.stack: list[_Frame] = []
        self.meta: dict[str, str] = {}
        self._title_parts: list[str] = []
        self._in_title = False

        self._parts: list[str] = []
        self._content_started = False
        self._content_done = False
        self._junk_depth = 0
        self._skip_depth = 0

    # -- helpers ----------------------------------------------------------- #

    def _collecting(self) -> bool:
        return (
            self._content_started
            and not self._content_done
            and self._junk_depth == 0
            and self._skip_depth == 0
        )

    def _is_content(self, tag: str, cls: str) -> bool:
        cls = cls.lower()
        if any(h in cls for h in self._content_hints):
            return True
        return tag in self._content_tags

    def _is_junk(self, cls: str) -> bool:
        cls = cls.lower()
        return any(h in cls for h in self._junk_hints)

    # -- HTMLParser callbacks ---------------------------------------------- #

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        adict = {k.lower(): (v or "") for k, v in attrs}

        if tag == "meta":
            self._handle_meta(adict)
            return
        if tag == "title":
            self._in_title = True
            return
        if tag in _VOID_TAGS:
            if tag == "br" and self._collecting():
                self._parts.append("\n")
            return

        frame = _Frame(tag)
        cls = f"{adict.get('class', '')} {adict.get('id', '')}"
        if tag in _SKIP_TAGS:
            frame.skip = True
            self._skip_depth += 1
        elif not self._content_done and not self._content_started and self._is_content(tag, cls):
            frame.content = True
            self._content_started = True
        elif self._content_started and self._is_junk(cls):
            frame.junk = True
            self._junk_depth += 1
        self.stack.append(frame)

        if tag in _BLOCK_TAGS and self._collecting():
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # e.g. <br/> or <meta .../> written XHTML-style.
        tag = tag.lower()
        if tag == "meta":
            self._handle_meta({k.lower(): (v or "") for k, v in attrs})
        elif tag == "br" and self._collecting():
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
            return
        if tag in _VOID_TAGS:
            return

        # Find the nearest matching open frame; pop everything above it too
        # (tolerates unclosed inline tags like <p> or <b>).
        idx = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].tag == tag:
                idx = i
                break
        if idx is None:
            if tag in _BLOCK_TAGS and self._collecting():
                self._parts.append("\n")
            return

        for frame in reversed(self.stack[idx:]):
            if frame.skip:
                self._skip_depth -= 1
            if frame.junk:
                self._junk_depth -= 1
            if frame.content:
                self._content_done = True  # the article body has closed
        del self.stack[idx:]

        if tag in _BLOCK_TAGS and self._collecting():
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        elif self._collecting():
            self._parts.append(data)

    # -- results ----------------------------------------------------------- #

    def _handle_meta(self, adict: dict[str, str]) -> None:
        key = (adict.get("property") or adict.get("name") or "").lower()
        content = adict.get("content", "")
        if not key or not content:
            return
        if key == "og:title":
            self.meta["og:title"] = content
        elif key in ("article:published_time", "article:published"):
            self.meta["published_time"] = content
        elif key in ("og:description", "description"):
            self.meta.setdefault("description", content)
        elif key == "og:url":
            self.meta["og:url"] = content

    def title_text(self) -> str:
        return _collapse_ws("".join(self._title_parts))

    def text(self) -> str:
        return _clean_block_text("".join(self._parts))


# --------------------------------------------------------------------------- #
# Text cleaning
# --------------------------------------------------------------------------- #

def _collapse_ws(text: str) -> str:
    return re.sub(r"[ \t \r\f\v]+", " ", text).strip()


def _clean_block_text(text: str) -> str:
    """Turn the raw collected chunks into readable paragraphs."""

    lines = [_collapse_ws(ln) for ln in text.split("\n")]
    paragraphs = [ln for ln in lines if ln]
    return "\n\n".join(paragraphs)


_SITE_SUFFIX_RE = re.compile(r"\s*[|»–\-]\s*(the inner ring|inrng)\s*$", re.IGNORECASE)
_SITE_PREFIX_RE = re.compile(r"^\s*(the inner ring|inrng)\s*[|»–\-]\s*", re.IGNORECASE)
_THOUGHTS_RE = re.compile(r'^\s*\d+\s+thoughts on\s+[“"]?', re.IGNORECASE)


def clean_title(title: str) -> str:
    title = _collapse_ws(title or "")
    title = _THOUGHTS_RE.sub("", title).strip(' "“”')
    title = _SITE_PREFIX_RE.sub("", title)
    title = _SITE_SUFFIX_RE.sub("", title)
    return title.strip()


# --------------------------------------------------------------------------- #
# Parsing a single stage page
# --------------------------------------------------------------------------- #

def parse_year_stage(url: str, title: str) -> tuple[int | None, int | None]:
    m = STAGE_URL_RE.search(url)
    if m:
        return int(m.group(1)), int(m.group(3))
    # Fall back to the title / any 4-digit year in the URL.
    year = None
    ym = re.search(r"/(\d{4})/", url)
    if ym:
        year = int(ym.group(1))
    sm = re.search(r"stage\s+(\d+)", title, re.IGNORECASE)
    stage = int(sm.group(1)) if sm else None
    return year, stage


def parse_date(published: str | None, url: str) -> str:
    if published:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", published)
        if m:
            return m.group(0)
    # No publish meta: fall back to the year/month embedded in the URL.
    m = STAGE_URL_RE.search(url)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return ""


def parse_stage(html_text: str, url: str) -> StageRecord | None:
    """Extract a :class:`StageRecord` from a stage-preview page's HTML."""

    ex = _TextExtractor()
    ex.feed(html_text)
    description = ex.text()

    # If the precise selectors found too little, retry allowing <article>/<main>.
    if len(description) < MIN_CONTENT_CHARS:
        ex2 = _TextExtractor(content_tags=frozenset({"article", "main"}))
        ex2.feed(html_text)
        if len(ex2.text()) > len(description):
            description = ex2.text()
            ex = ex2

    title = clean_title(ex.meta.get("og:title") or ex.title_text())
    edition, stage = parse_year_stage(url, title)
    if edition is None or stage is None:
        return None

    date = parse_date(ex.meta.get("published_time"), url)
    return StageRecord(
        edition=edition,
        stage=stage,
        title=title or f"Tour de France {edition} Stage {stage} Preview",
        url=url,
        date=date,
        description=description,
        word_count=len(description.split()),
    )


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

def build_session(user_agent: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def http_get(
    session: requests.Session,
    url: str,
    *,
    timeout: float,
    retries: int,
    verbose: bool = False,
) -> bytes | None:
    """GET ``url`` with exponential backoff. Returns the raw body or ``None``."""

    backoff = 2.0
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, timeout=timeout)
        except requests.RequestException as exc:
            if verbose:
                print(f"    ! {url} -> {exc.__class__.__name__} (attempt {attempt}/{retries})")
            if attempt == retries:
                return None
            time.sleep(backoff)
            backoff *= 2
            continue

        if resp.status_code == 200:
            return resp.content
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            if verbose:
                print(f"    ! {url} -> HTTP {resp.status_code}, retrying ({attempt}/{retries})")
            time.sleep(backoff)
            backoff *= 2
            continue
        if verbose:
            print(f"    ! {url} -> HTTP {resp.status_code}")
        return None
    return None


def http_get_text(session: requests.Session, url: str, **kw) -> str | None:
    body = http_get(session, url, **kw)
    if body is None:
        return None
    if url.lower().endswith(".gz"):
        try:
            body = gzip.decompress(body)
        except OSError:
            pass
    return body.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #

def _iter_locs(xml: str) -> list[str]:
    return [html.unescape(m.strip()) for m in re.findall(r"<loc>\s*(.*?)\s*</loc>", xml, re.IGNORECASE | re.DOTALL)]


def expand_sitemap(
    session: requests.Session,
    url: str,
    xml: str,
    seen: set[str],
    *,
    depth: int,
    http_kw: dict,
    verbose: bool,
) -> list[str]:
    """Return every page URL reachable from a sitemap or sitemap index."""

    locs = _iter_locs(xml)
    if "<sitemapindex" not in xml.lower():
        return locs  # a plain <urlset>: these are page URLs

    pages: list[str] = []
    for loc in locs:
        if loc in seen or depth >= 4:
            continue
        seen.add(loc)
        # Skip sub-sitemaps that clearly won't hold stage posts (saves requests).
        low = loc.lower()
        if any(k in low for k in ("image", "video", "author", "category", "tag", "product")):
            continue
        if verbose:
            print(f"    sitemap: {loc}")
        sub = http_get_text(session, loc, **http_kw)
        if sub:
            pages.extend(expand_sitemap(session, loc, sub, seen, depth=depth + 1, http_kw=http_kw, verbose=verbose))
    return pages


def discover_via_sitemap(session: requests.Session, base: str, *, http_kw: dict, verbose: bool) -> list[str]:
    for path in SITEMAP_PATHS:
        url = base.rstrip("/") + path
        xml = http_get_text(session, url, **http_kw)
        if xml and "<loc>" in xml.lower():
            if verbose:
                print(f"  using sitemap: {url}")
            return expand_sitemap(session, url, xml, {url}, depth=0, http_kw=http_kw, verbose=verbose)
    if verbose:
        print("  no sitemap found")
    return []


def harvest_stage_links(page_html: str) -> list[str]:
    """Pull every stage-preview URL out of an index/guide page's HTML."""

    found = set(re.findall(r'href=["\']([^"\']+)["\']', page_html))
    # Also catch bare URLs printed in text.
    found.update(re.findall(r'https?://(?:www\.)?inrng\.com/\d{4}/\d{2}/[^\s"\'<>]+', page_html))
    return [html.unescape(u) for u in found if STAGE_URL_RE.search(html.unescape(u))]


def normalize_url(u: str) -> str:
    u = html.unescape(u.strip())
    u = u.split("#", 1)[0].split("?", 1)[0]
    if not u.endswith("/"):
        u += "/"
    return u


def collect_stage_urls(
    session: requests.Session,
    *,
    base: str,
    use_sitemap: bool,
    seed_urls: list[str],
    url_list: list[str],
    http_kw: dict,
    verbose: bool,
) -> dict[tuple[int, int], str]:
    """Discover stage URLs and return a {(edition, stage): url} map (deduped)."""

    candidates: list[str] = list(url_list)

    if use_sitemap:
        print("Discovering stages via sitemap…")
        pages = discover_via_sitemap(session, base, http_kw=http_kw, verbose=verbose)
        matched = [p for p in pages if STAGE_URL_RE.search(p)]
        print(f"  sitemap: {len(pages)} URLs, {len(matched)} look like stage previews")
        candidates.extend(matched)

    for seed in seed_urls:
        page = http_get_text(session, seed, **http_kw)
        if not page:
            print(f"  seed unreachable: {seed}")
            continue
        links = harvest_stage_links(page)
        print(f"  seed {seed}: {len(links)} stage links")
        candidates.extend(links)

    # Dedupe by (edition, stage). Prefer the shortest URL when a stage appears
    # more than once (usually the cleaner canonical permalink).
    by_key: dict[tuple[int, int], str] = {}
    for raw in candidates:
        url = normalize_url(raw)
        m = STAGE_URL_RE.search(url)
        if not m:
            continue
        key = (int(m.group(1)), int(m.group(3)))
        if key not in by_key or len(url) < len(by_key[key]):
            by_key[key] = url
    return by_key


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def scrape_all(
    stage_urls: dict[tuple[int, int], str],
    session: requests.Session,
    *,
    delay: float,
    http_kw: dict,
    verbose: bool,
) -> list[StageRecord]:
    records: dict[tuple[int, int], StageRecord] = {}
    ordered = sorted(stage_urls.items())
    total = len(ordered)
    for i, ((edition, stage), url) in enumerate(ordered, start=1):
        print(f"[{i}/{total}] {edition} stage {stage:>2}  {url}")
        page = http_get_text(session, url, **http_kw)
        if not page:
            print("    ! could not fetch — skipping")
            continue
        rec = parse_stage(page, url)
        if rec is None or not rec.description:
            print("    ! no description extracted — skipping")
            continue
        if verbose:
            preview = rec.description[:120].replace("\n", " ")
            print(f'    ok: "{rec.title}" ({rec.word_count} words) — {preview}…')
        key = (rec.edition, rec.stage)
        # Keep the richer text if we somehow scrape the same stage twice.
        if key not in records or rec.word_count > records[key].word_count:
            records[key] = rec
        if delay and i < total:
            time.sleep(delay)
    return sorted(records.values(), key=lambda r: (r.edition, r.stage))


def write_output(records: list[StageRecord], out: Path, *, source: str, indent: int) -> None:
    editions = sorted({r.edition for r in records})
    payload = {
        "source": source,
        "scraped_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "editions": editions,
        "totalStages": len(records),
        "stages": [asdict(r) for r in records],
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")


def summarize(records: list[StageRecord]) -> None:
    by_edition: dict[int, list[int]] = {}
    for r in records:
        by_edition.setdefault(r.edition, []).append(r.stage)
    print("\nSummary by edition:")
    for edition in sorted(by_edition):
        stages = sorted(by_edition[edition])
        gaps = sorted(set(range(1, max(stages) + 1)) - set(stages)) if stages else []
        gap_note = f"  (missing {gaps})" if gaps else ""
        print(f"  {edition}: {len(stages)} stages{gap_note}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"output JSON path (default: {DEFAULT_OUT})")
    parser.add_argument("--base-url", default=BASE_URL, help="site base URL")
    parser.add_argument("--no-sitemap", dest="sitemap", action="store_false",
                        help="do not crawl the XML sitemap for discovery")
    parser.add_argument("--seed-url", dest="seed_urls", action="append", default=None,
                        help="index/guide page to harvest stage links from (repeatable)")
    parser.add_argument("--url-list", type=Path, default=None,
                        help="file with explicit stage URLs, one per line (skips discovery)")
    parser.add_argument("--years", type=int, nargs="+", default=None,
                        help="only scrape these editions, e.g. --years 2024 2025")
    parser.add_argument("--year-min", type=int, default=None, help="oldest edition to include")
    parser.add_argument("--year-max", type=int, default=None, help="newest edition to include")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds between requests (be polite)")
    parser.add_argument("--timeout", type=float, default=30.0, help="per-request timeout (s)")
    parser.add_argument("--retries", type=int, default=3, help="retries per request")
    parser.add_argument("--limit", type=int, default=None, help="stop after N stages (smoke test)")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="HTTP User-Agent header")
    parser.add_argument("--indent", type=int, default=2, help="JSON indent")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--list-only", action="store_true",
                        help="only discover and print stage URLs; do not fetch pages")
    args = parser.parse_args(argv)

    session = build_session(args.user_agent)
    http_kw = {"timeout": args.timeout, "retries": args.retries, "verbose": args.verbose}

    url_list: list[str] = []
    if args.url_list:
        url_list = [ln.strip() for ln in args.url_list.read_text(encoding="utf-8").splitlines()
                    if ln.strip() and not ln.startswith("#")]

    seed_urls = args.seed_urls if args.seed_urls is not None else DEFAULT_SEED_URLS

    stage_urls = collect_stage_urls(
        session,
        base=args.base_url,
        use_sitemap=args.sitemap and not url_list,
        seed_urls=seed_urls if not url_list else [],
        url_list=url_list,
        http_kw=http_kw,
        verbose=args.verbose,
    )

    # Filter editions.
    def keep(year: int) -> bool:
        if args.years is not None and year not in args.years:
            return False
        if args.year_min is not None and year < args.year_min:
            return False
        if args.year_max is not None and year > args.year_max:
            return False
        return True

    stage_urls = {k: v for k, v in stage_urls.items() if keep(k[0])}
    if args.limit is not None:
        stage_urls = dict(sorted(stage_urls.items())[: args.limit])

    editions = sorted({k[0] for k in stage_urls})
    print(f"\nFound {len(stage_urls)} stage(s) across {len(editions)} edition(s): {editions}")

    if not stage_urls:
        print("Nothing to scrape. Try --seed-url with a stage-guide page, or --url-list.")
        return 1

    if args.list_only:
        for (edition, stage), url in sorted(stage_urls.items()):
            print(f"{edition}\tstage {stage}\t{url}")
        return 0

    records = scrape_all(stage_urls, session, delay=args.delay, http_kw=http_kw, verbose=args.verbose)
    write_output(records, args.out, source=f"{args.base_url}/tour/", indent=args.indent)
    summarize(records)
    print(f"\nWrote {len(records)} stage(s) to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
