#!/usr/bin/env python
"""Offline tests for scripts/scrape_tour_data.py.

The scraper talks to a live site, so these tests exercise the *pure* parts —
URL matching, link harvesting, sitemap parsing and (most importantly) the
WordPress content extractor — against realistic HTML/XML fixtures. No network.

Run directly (no pytest needed):

    python tests/test_scrape_tour_data.py

…or with pytest:

    pytest tests/test_scrape_tour_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import scrape_tour_data as s  # noqa: E402


# A stage page shaped like The Inner Ring's WordPress output: a clean article
# body inside .entry-content, wrapped in share buttons, related-posts and a
# comment thread that must NOT leak into the description.
STAGE_HTML = """<!doctype html>
<html lang="en-GB">
<head>
  <meta charset="utf-8"/>
  <title>The Inner Ring | Tour de France Stage 1 Preview</title>
  <meta property="og:title" content="Tour de France Stage 1 Preview"/>
  <meta property="og:type" content="article"/>
  <meta property="article:published_time" content="2024-06-29T05:00:12+00:00"/>
  <meta property="og:url" content="https://inrng.com/2024/06/tour-de-france-stage-1/"/>
</head>
<body class="single single-post">
  <header id="site-header"><nav class="main-nav"><a href="/">Home</a></nav></header>
  <article class="post">
    <h1 class="entry-title">Tour de France Stage 1 Preview</h1>
    <div class="entry-meta">Posted on <time>29 June 2024</time> by inrng</div>
    <div class="entry-content">
      <p>The Grand D&eacute;part in Florence and a hilly stage to Rimini with
      seven categorised climbs along the way.</p>
      <h2>The Route</h2>
      <p>206km with the Barbotto climb, a wall that averages
      <strong>7.6%</strong> but hits 18% near the top.<br/>Then a run to the coast.</p>
      <p>See the <a href="https://inrng.com/roads/">roads to ride</a> post for more.</p>
      <div class="sharedaddy sd-block sd-social">
        <h3 class="sd-title">Share this:</h3><a href="#">Twitter</a><a href="#">Facebook</a>
      </div>
      <div class="jp-relatedposts"><h3>Related</h3><p>Stage 2 Preview</p></div>
    </div>
  </article>
  <div id="comments">
    <h3>56 thoughts on Tour de France Stage 1 Preview</h3>
    <ol class="commentlist">
      <li class="comment"><div class="comment-body"><p>Great preview as always!</p></div></li>
      <li class="comment"><div class="comment-body"><p>Pogacar to win.</p></div></li>
    </ol>
    <div id="respond" class="comment-respond">
      <h3>Leave a Reply</h3><form><textarea></textarea></form>
    </div>
  </div>
  <footer id="site-footer"><p>Copyright inrng</p></footer>
</body>
</html>"""


def _check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok  {name}")
    else:
        raise AssertionError(f"FAILED: {name} {('- ' + detail) if detail else ''}")


def test_stage_url_regex() -> None:
    matches = {
        "https://inrng.com/2026/07/tour-de-france-stage-1/": (2026, 1),
        "https://inrng.com/2025/07/tour-de-france-stage-2-preview-boulogne/": (2025, 2),
        "https://inrng.com/2023/07/tour-de-france-stage-19-preview-poligny/": (2023, 19),
        "https://inrng.com/2020/08/tour-de-france-stage-1-preview-nice/": (2020, 1),
        "https://inrng.com/2019/07/tour-de-france-2019-stage-1-preview-brussels/": (2019, 1),
    }
    for url, (year, stage) in matches.items():
        m = s.STAGE_URL_RE.search(url)
        _check(f"matches {url}", m is not None)
        _check(f"  -> ({year},{stage})", (int(m.group(1)), int(m.group(3))) == (year, stage),
               detail=f"got ({m.group(1)},{m.group(3)})")

    non_matches = [
        "https://inrng.com/2026/06/tour-de-france-2026-stage-guide/",   # guide, not a stage
        "https://inrng.com/2025/06/tour-de-france-2025-ical-calendar/",
        "https://inrng.com/2025/07/tour-de-france-2025-preview/",       # contenders preview
        "https://inrng.com/about/",
    ]
    for url in non_matches:
        _check(f"rejects {url}", s.STAGE_URL_RE.search(url) is None)


def test_harvest_stage_links() -> None:
    index = """
      <ul>
        <li><a href="https://inrng.com/2024/06/tour-de-france-stage-1/">Stage 1</a></li>
        <li><a href='https://inrng.com/2024/07/tour-de-france-stage-2-preview-cesenatico/'>Stage 2</a></li>
        <li><a href="https://inrng.com/2024/06/tour-de-france-2024-stage-guide/">Guide</a></li>
        <li><a href="/about/">About</a></li>
      </ul>
      Bare link: https://inrng.com/2024/07/tour-de-france-stage-21-preview-nice/ ok
    """
    links = s.harvest_stage_links(index)
    keys = {s.STAGE_URL_RE.search(u).group(3) for u in links}
    _check("harvested 3 stage links", len(set(links)) == 3, detail=str(links))
    _check("found stages 1,2,21", keys == {"1", "2", "21"}, detail=str(keys))
    _check("guide excluded", all("stage-guide" not in u for u in links))


def test_sitemap_parsing() -> None:
    index_xml = """<?xml version="1.0"?>
      <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <sitemap><loc>https://inrng.com/post-sitemap.xml</loc></sitemap>
        <sitemap><loc>https://inrng.com/image-sitemap.xml</loc></sitemap>
      </sitemapindex>"""
    _check("detects index", "<sitemapindex" in index_xml.lower())
    locs = s._iter_locs(index_xml)
    _check("index has 2 locs", len(locs) == 2, detail=str(locs))

    urlset_xml = """<?xml version="1.0"?>
      <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://inrng.com/2022/07/tour-de-france-stage-1-preview-copenhagen/</loc></url>
        <url><loc>https://inrng.com/2022/07/tour-de-france-stage-2-preview-roskilde/</loc></url>
        <url><loc>https://inrng.com/2022/07/some-other-post/</loc></url>
      </urlset>"""
    page_urls = s._iter_locs(urlset_xml)
    stage_urls = [u for u in page_urls if s.STAGE_URL_RE.search(u)]
    _check("urlset yields 3 locs", len(page_urls) == 3)
    _check("2 are stage previews", len(stage_urls) == 2, detail=str(stage_urls))


def test_normalize_url() -> None:
    cases = {
        "https://inrng.com/2024/06/tour-de-france-stage-1": "https://inrng.com/2024/06/tour-de-france-stage-1/",
        "https://inrng.com/2024/06/tour-de-france-stage-1/#comments": "https://inrng.com/2024/06/tour-de-france-stage-1/",
        "https://inrng.com/2024/06/tour-de-france-stage-1/?utm=x": "https://inrng.com/2024/06/tour-de-france-stage-1/",
    }
    for raw, want in cases.items():
        _check(f"normalize {raw}", s.normalize_url(raw) == want, detail=s.normalize_url(raw))


def test_parse_stage_extracts_clean_description() -> None:
    url = "https://inrng.com/2024/06/tour-de-france-stage-1/"
    rec = s.parse_stage(STAGE_HTML, url)
    _check("record returned", rec is not None)
    assert rec is not None

    _check("title clean", rec.title == "Tour de France Stage 1 Preview", detail=rec.title)
    _check("edition 2024", rec.edition == 2024)
    _check("stage 1", rec.stage == 1)
    _check("date parsed", rec.date == "2024-06-29", detail=rec.date)

    desc = rec.description
    # Real article content is present…
    _check("has intro", "Grand Départ in Florence" in desc, detail=desc[:200])
    _check("entity decoded", "Départ" in desc and "&eacute;" not in desc)
    _check("has route heading", "The Route" in desc)
    _check("has climb detail", "Barbotto climb" in desc and "7.6%" in desc)
    _check("<br> split kept text", "run to the coast" in desc)
    _check("inline link text kept", "roads to ride" in desc)

    # …and none of the junk leaked in.
    for junk in ["Share this:", "Twitter", "Related", "Stage 2 Preview",
                 "56 thoughts", "Great preview", "Pogacar to win", "Leave a Reply",
                 "Copyright inrng", "Home"]:
        _check(f"excludes junk: {junk!r}", junk not in desc, detail=desc)

    # Paragraph structure preserved.
    _check("multi-paragraph", desc.count("\n\n") >= 2)
    _check("reasonable length", 100 < len(desc) < 2000, detail=str(len(desc)))


def test_parse_stage_article_fallback() -> None:
    # A theme with no .entry-content class: the <article> fallback must kick in.
    html = """<html><head><title>Tour de France Stage 5 Preview</title>
      <meta property="og:title" content="Tour de France Stage 5 Preview"/></head>
      <body><article><h1>Stage 5</h1>
      <p>A long paragraph of preview text that easily clears the minimum content
      threshold so the parser is confident this article body is the real one and
      not a stray snippet, describing a flat sprint stage across the plains with a
      nervous run-in to the line where the sprinters' teams will fight for
      position on the wide finishing boulevard.</p>
      </article></body></html>"""
    rec = s.parse_stage(html, "https://inrng.com/2024/07/tour-de-france-stage-5-preview-town/")
    _check("fallback record", rec is not None)
    assert rec is not None
    _check("fallback got text", "flat sprint stage" in rec.description, detail=rec.description[:120])
    _check("fallback stage 5", rec.stage == 5)


def test_clean_title() -> None:
    cases = {
        "The Inner Ring | Tour de France Stage 1 Preview": "Tour de France Stage 1 Preview",
        "Tour de France Stage 1 Preview | The Inner Ring": "Tour de France Stage 1 Preview",
        '56 thoughts on "Tour de France Stage 1 Preview"': "Tour de France Stage 1 Preview",
    }
    for raw, want in cases.items():
        got = s.clean_title(raw)
        _check(f"clean_title({raw!r})", got == want, detail=got)


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    print(f"Running {len(tests)} test group(s)…\n")
    failures = 0
    for t in tests:
        print(f"{t.__name__}:")
        try:
            t()
        except AssertionError as exc:
            print(f"  {exc}")
            failures += 1
        print()
    if failures:
        print(f"❌ {failures} test group(s) failed")
        return 1
    print("✅ all tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
