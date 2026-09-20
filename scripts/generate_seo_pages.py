"""Generate SEO pages from Supabase data.

Produces:
- Embedded static JSON in docs/index.html (50 newest positions)
- <noscript> fallback with 30 positions as semantic HTML
- docs/positions.html + docs/positions/<n>.html - active positions only;
  pagination pages after page one are crawlable but noindex.
- docs/area/<slug>.html, docs/country/<slug>.html - facet hubs. These are the
  real ranking targets ("Biology PhD positions in Germany" beats 214 separate
  38-word pages competing with each other).
- docs/p/<slug>.html - active and archived pages; only complete active jobs get
  JobPosting markup and index permission
- docs/sitemap.xml plus docs/sitemaps/core.xml and jobs.xml
"""

import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client

from src.seo import (
    effective_deadline,
    is_position_active,
    is_seo_eligible,
    lifecycle_state,
    normalize_http_url,
)

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
# BASE_URL is the canonical public URL used in sitemap/JSON-LD.
# phdsky.org (Vercel) is the single canonical home — gh-pages redirects here.
BASE_URL = os.environ.get("SITE_BASE_URL") or "https://phdsky.org/"
if not BASE_URL.endswith("/"):
    BASE_URL += "/"
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

# position_type → schema.org employmentType enum.
# PhD/Master are coded INTERN per Google's example for trainee/graduate roles
# (none of our position types map cleanly to FULL_TIME for studentships).
EMPLOYMENT_TYPE_MAP = {
    "PhD Student": "INTERN",
    "Master Student": "INTERN",
    "Postdoc": "FULL_TIME",
    "Research Assistant": "FULL_TIME",
}

# /positions listing. The listing contains active positions only. Pagination
# still provides internal discovery, but pages after page one are noindex.
POSITIONS_PER_PAGE = 200
# Facet hubs list only their most recent active slice — they exist to rank and
# pass links, not to mirror the full active listing.
FACET_MAX_ITEMS = 200
FACET_MIN_POSITIONS = 5  # below this a hub is thin content; skip it
# Catch-all discipline labels that make meaningless landing pages — nobody
# searches "General call PhD positions". They stay as tags, just not as hubs.
FACET_EXCLUDE_DISCIPLINES = {"General call", "Other"}
LISTING_PREVIEW_CHARS = 300

POSITION_SELECT_FIELDS = (
    "uri,created_at,disciplines,country,position_type,user_handle,message,url,"
    "is_verified_job,job_title,hiring_organization,application_url,"
    "application_deadline,location_text,seo_enriched_at"
)


COUNTRY_ISO = {
    "Australia": "AU", "Austria": "AT", "Belgium": "BE", "Brazil": "BR",
    "Canada": "CA", "Chile": "CL", "China": "CN", "Colombia": "CO",
    "Czech Republic": "CZ", "Denmark": "DK", "Egypt": "EG", "Estonia": "EE",
    "Finland": "FI", "France": "FR", "Germany": "DE", "Greece": "GR",
    "Hong Kong": "HK", "Hungary": "HU", "Iceland": "IS", "India": "IN",
    "Indonesia": "ID", "Ireland": "IE", "Israel": "IL", "Italy": "IT",
    "Japan": "JP", "Kenya": "KE", "Latvia": "LV", "Lithuania": "LT",
    "Luxembourg": "LU", "Malaysia": "MY", "Mexico": "MX", "Netherlands": "NL",
    "New Zealand": "NZ", "Nigeria": "NG", "Norway": "NO", "Pakistan": "PK",
    "Peru": "PE", "Philippines": "PH", "Poland": "PL", "Portugal": "PT",
    "Romania": "RO", "Saudi Arabia": "SA", "Singapore": "SG",
    "Slovakia": "SK", "Slovenia": "SI", "South Africa": "ZA",
    "South Korea": "KR", "Spain": "ES", "Sweden": "SE", "Switzerland": "CH",
    "Taiwan": "TW", "Thailand": "TH", "Turkey": "TR", "UAE": "AE",
    "UK": "GB", "USA": "US", "Ukraine": "UA", "Vietnam": "VN",
}


def escape_html(text):
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def json_for_script(data, **dumps_kwargs):
    """json.dumps() escaped for safe embedding inside an HTML <script> element.

    json.dumps leaves `<`, `>` and `&` untouched, so post text containing the
    literal `</script>` would terminate the element early and let the remainder
    of an attacker-authored Bluesky post execute as markup. Position `message`
    is verbatim user content, so every <script> block we build from it must go
    through here.

    The \\uXXXX forms are valid JSON and JSON.parse restores the original
    characters, so consumers (docs/app.js, Google's parsers) need no change.
    """
    return (
        json.dumps(data, **dumps_kwargs)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def extract_slug(uri):
    """Return a URL-safe slug from a position URI, or None if not derivable.

    Bluesky URIs look like `at://did:plc:abc/app.bsky.feed.post/3mldoq7ee5k2s`,
    so the post ID lives in the trailing segment. Sanitize defensively to keep
    it filename-safe.
    """
    if not uri:
        return None
    raw = uri.rsplit("/", 1)[-1]
    slug = re.sub(r"[^a-zA-Z0-9_-]", "", raw)
    return slug or None


def build_job_posting(pos, canonical_url=None):
    """Return a JSON-LD JobPosting dict for a position, or None if it can't be
    represented validly (missing country mapping, missing required fields).

    `canonical_url` lets callers point JobPosting.url at the per-job landing
    page (`/p/<slug>`) instead of the original Bluesky post — that's where
    Google Jobs should send users so they see a structured listing first.

    Skipping is preferable to emitting partial markup — Google's rich-results
    validator marks the whole page down on a single broken JobPosting.
    """
    if not is_seo_eligible(pos):
        return None

    country = pos.get("country") or ""
    iso = COUNTRY_ISO.get(country)
    if not iso:
        return None

    created = pos.get("created_at") or ""
    if not created:
        return None

    types = pos.get("position_type") or []
    employment_type = EMPLOYMENT_TYPE_MAP.get(types[0]) if types else None

    title = pos["job_title"].strip()
    organization = pos["hiring_organization"].strip()
    description = pos.get("message") or ""
    listing_url = canonical_url or pos.get("application_url") or ""

    jp = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        # JSON-LD is serialized safely below; schema text must remain identical
        # to the visible posting instead of being HTML-entity encoded.
        "description": description,
        "datePosted": created,
        "employmentType": employment_type,
        "directApply": False,
        "url": listing_url,
        "hiringOrganization": {
            "@type": "Organization",
            "name": organization,
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": iso,
            },
        },
    }
    deadline = effective_deadline(pos)
    if deadline:
        jp["validThrough"] = f"{deadline.isoformat()}T23:59:59Z"
    location_text = (pos.get("location_text") or "").strip()
    if location_text and location_text.lower() != country.lower():
        jp["jobLocation"]["address"]["addressLocality"] = location_text
    if not employment_type:
        jp.pop("employmentType")
    if not listing_url:
        jp.pop("url")
    return jp


def fetch_positions(client, limit=500):
    result = (
        client.table("phd_positions")
        .select(POSITION_SELECT_FIELDS)
        .eq("is_verified_job", True)
        .is_("duplicate_of", "null")
        .gte("indexed_at", "2026-01-27")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data


def fetch_all_canonical_positions(client, page_size=1000):
    """Paginated fetch of every verified canonical position the frontend would show.

    Mirrors the filter set used by docs/app.js fetchSupabasePositions() so the
    static snapshot matches what users would see if they hit Supabase live.
    """
    all_rows = []
    start = 0
    while True:
        result = (
            client.table("phd_positions")
            .select(POSITION_SELECT_FIELDS)
            .eq("is_verified_job", True)
            .is_("duplicate_of", "null")
            .gte("indexed_at", "2026-01-27")
            .order("created_at", desc=True)
            .range(start, start + page_size - 1)
            .execute()
        )
        batch = result.data or []
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return all_rows


def fetch_all_duplicates(client, page_size=1000):
    """Paginated fetch of all rows that are marked as duplicates of a canonical post."""
    all_rows = []
    start = 0
    while True:
        result = (
            client.table("phd_positions")
            .select("uri, url, user_handle, created_at, duplicate_of")
            .not_.is_("duplicate_of", "null")
            .gte("indexed_at", "2026-01-27")
            .range(start, start + page_size - 1)
            .execute()
        )
        batch = result.data or []
        all_rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return all_rows


def get_total_count(client):
    result = (
        client.table("phd_positions")
        .select("uri", count="exact")
        .eq("is_verified_job", True)
        .is_("duplicate_of", "null")
        .gte("indexed_at", "2026-01-27")
        .execute()
    )
    return result.count



def generate_noscript_html(positions):
    items = []
    for pos in positions[:30]:
        slug = extract_slug(pos.get("uri"))
        date = pos.get("created_at", "")[:10]
        country = pos.get("country") or ""
        country_html = f" | {escape_html(country)}" if country and country != "Unknown" else ""
        job_title = escape_html(pos.get("job_title") or "Academic research position")
        employer = escape_html(pos.get("hiring_organization") or "")
        message = escape_html((pos.get("message") or "")[:300])
        handle = escape_html(pos.get("user_handle") or "")
        url = normalize_http_url(pos.get("url"))

        heading = job_title + (f" &mdash; {employer}" if employer else "")
        if slug:
            heading = f'<a href="/p/{slug}">{heading}</a>'

        cta_parts = []
        if slug:
            cta_parts.append(f'<a href="/p/{slug}">Read more</a>')
        application_url = normalize_http_url(pos.get("application_url"))
        if application_url:
            cta_parts.append(f'<a href="{escape_html(application_url)}">Apply on the official site</a>')
        if url:
            cta_parts.append(f'<a href="{escape_html(url)}">Source post</a>')
        cta_html = " | ".join(cta_parts)

        items.append(
            f"<article><h3>{heading}</h3>"
            f"<p><small>{date}{country_html} | @{handle}</small></p>"
            f"<p>{message}</p>"
            f"{cta_html}</article>"
        )

    return (
        "<noscript>\n"
        '<div style="max-width:800px;margin:2rem auto;padding:0 1rem;color:#e2e8f0;">\n'
        "<h2>Recent PhD &amp; Postdoc Positions</h2>\n"
        + "\n".join(items)
        + '\n<p><a href="/positions">View all positions</a></p>\n'
        "</div>\n"
        "</noscript>"
    )


def update_index_html(positions, total_count, now=None):
    positions = [p for p in positions if is_position_active(p, now=now)]
    total_count = len(positions) if total_count is None else total_count
    index_path = os.path.join(DOCS_DIR, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    static_positions = []
    for pos in positions[:50]:
        static_positions.append({
            "uri": pos.get("uri", ""),
            "created_at": pos.get("created_at", ""),
            "disciplines": pos.get("disciplines") or [],
            "country": pos.get("country") or "",
            "position_type": pos.get("position_type") or [],
            "user_handle": pos.get("user_handle", ""),
            "message": pos.get("message", ""),
            "url": pos.get("url", ""),
            "is_verified_job": pos.get("is_verified_job") is True,
            "job_title": pos.get("job_title"),
            "hiring_organization": pos.get("hiring_organization"),
            "application_url": pos.get("application_url"),
            "application_deadline": (
                effective_deadline(pos).isoformat() if effective_deadline(pos) else None
            ),
            "location_text": pos.get("location_text"),
        })

    static_data = json_for_script(
        {"positions": static_positions, "total": total_count},
        separators=(",", ":"),
    )

    static_block = (
        "<!-- STATIC_DATA_START -->\n"
        f'    <script id="static-positions" type="application/json">{static_data}</script>\n'
        "    <!-- STATIC_DATA_END -->"
    )

    noscript_block = (
        "<!-- SEO_NOSCRIPT_START -->\n"
        f"    {generate_noscript_html(positions)}\n"
        "    <!-- SEO_NOSCRIPT_END -->"
    )

    # Replace or insert static data block
    static_pattern = r"<!-- STATIC_DATA_START -->.*?<!-- STATIC_DATA_END -->"
    match = re.search(static_pattern, html, re.DOTALL)
    if match:
        html = html[:match.start()] + static_block + html[match.end():]
    else:
        html = html.replace(
            "    <!-- App script -->",
            f"    {static_block}\n\n    <!-- App script -->",
        )

    # Replace or insert noscript block
    noscript_pattern = r"<!-- SEO_NOSCRIPT_START -->.*?<!-- SEO_NOSCRIPT_END -->"
    match = re.search(noscript_pattern, html, re.DOTALL)
    if match:
        html = html[:match.start()] + noscript_block + html[match.end():]
    else:
        html = html.replace(
            "    <!-- App script -->",
            f"    {noscript_block}\n\n    <!-- App script -->",
        )

    with open(index_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    print(f"Updated index.html: {len(static_positions)} embedded positions, total={total_count}")


def slugify(text):
    """URL-safe slug for facet pages ('Chemistry & Materials Science' -> 'chemistry-materials-science')."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or None


def _collection_schema(name, description, canonical, positions):
    """CollectionPage + ItemList.

    Replaces the old `Dataset` markup, which described this as a research
    dataset for Google Dataset Search — the wrong type for a job listing, and it
    also asserted a CC0 license over third-party Bluesky posts we don't own.
    ItemList is what Google actually reads on a listing page, and it points at
    the per-job pages that carry the JobPosting markup.
    """
    items = []
    for pos in positions:
        if not is_seo_eligible(pos):
            continue
        slug = extract_slug(pos.get("uri"))
        if not slug:
            continue
        items.append({
            "@type": "ListItem",
            "position": len(items) + 1,
            "url": f"{BASE_URL}p/{slug}",
        })
    return {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": name,
        "description": description,
        "url": canonical,
        "isPartOf": {"@type": "WebSite", "name": "PhD Sky", "url": BASE_URL},
        "mainEntity": {
            "@type": "ItemList",
            "numberOfItems": len(items),
            "itemListElement": items,
        },
    }


_LISTING_CSS = """
:root{--paper:#f3f5f2;--card:#fff;--ink:#18201d;--mut:#55625c;--rule:#c8d0cb;--green:#18594a;--blue:#315f78;--red:#b54632}
*{box-sizing:border-box}
body{font-family:Atkinson Hyperlegible,system-ui,sans-serif;background:var(--paper);color:var(--ink);margin:0;padding:2rem 1rem;line-height:1.6}
.container{max-width:820px;margin:0 auto}
h1,h2,h3{font-family:Literata,Georgia,serif}h1{font-size:1.75rem;margin:0 0 .4rem;line-height:1.25}
.subtitle{color:var(--mut);font-size:.95rem;margin:0 0 1.5rem}
a{color:var(--green);text-underline-offset:3px}a:hover{color:var(--red)}
.back-link{display:inline-block;margin-bottom:1.25rem;font-size:.9rem}
.facets{background:var(--card);border:1px solid var(--rule);padding:1rem 1.25rem;margin-bottom:1.5rem}
.facets h2{font-size:.78rem;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin:0 0 .5rem}
.facets ul{list-style:none;margin:0 0 1rem;padding:0;display:flex;flex-wrap:wrap;gap:.35rem .8rem}
.facets ul:last-child{margin-bottom:0}
.facets li{font-size:.85rem}
article{background:var(--card);border-top:3px solid var(--green);border-right:1px solid var(--rule);border-bottom:1px solid var(--rule);border-left:1px solid var(--rule);padding:1.25rem;margin-bottom:1rem}
article h3{font-size:1rem;margin:0 0 .4rem}
article h3 a{color:var(--ink);text-decoration:none}
article h3 a:hover{color:var(--green)}
.meta{font-size:.82rem;color:var(--mut);margin:0 0 .6rem}
.msg{font-size:.94rem;margin:0 0 .6rem;white-space:pre-wrap}
.cta{font-size:.85rem;margin:0}
nav.pager{margin:2rem 0 1rem;font-size:.9rem}
nav.pager .rel{display:flex;justify-content:space-between;gap:1rem;margin-bottom:.75rem}
nav.pager .nums{display:flex;flex-wrap:wrap;gap:.3rem .6rem;color:var(--mut);font-size:.85rem}
nav.pager .nums .cur{color:var(--ink);font-weight:600}
footer{margin-top:2rem;padding-top:1.25rem;border-top:1px solid var(--rule);font-size:.85rem;color:var(--mut)}
:focus-visible{outline:3px solid var(--red);outline-offset:3px}
"""


def _position_article(pos):
    """One listing entry. Links to the per-job page, which holds JobPosting."""
    slug = extract_slug(pos.get("uri"))
    date = (pos.get("created_at") or "")[:10]
    country = pos.get("country") or ""
    country_html = f" &middot; {escape_html(country)}" if country and country != "Unknown" else ""
    title = pos.get("job_title") or "Academic research position"
    organization = pos.get("hiring_organization") or ""
    full_message = pos.get("message") or ""
    preview = full_message[:LISTING_PREVIEW_CHARS] + (
        "..." if len(full_message) > LISTING_PREVIEW_CHARS else "")
    message = escape_html(preview)
    handle = escape_html(pos.get("user_handle") or "")
    url = normalize_http_url(pos.get("url"))

    heading_inner = escape_html(title)
    if organization:
        heading_inner += f" &mdash; {escape_html(organization)}"
    heading = f'<a href="/p/{slug}">{heading_inner}</a>' if slug else heading_inner

    cta = []
    if slug:
        cta.append(f'<a href="/p/{slug}">Read full posting &rarr;</a>')
    application_url = normalize_http_url(pos.get("application_url"))
    if application_url:
        cta.append(
            f'<a href="{escape_html(application_url)}" rel="nofollow">Apply on the official site</a>'
        )
    if url:
        cta.append(f'<a href="{escape_html(url)}" rel="nofollow">Source post</a>')

    return (
        "<article>\n"
        f"  <h3>{heading}</h3>\n"
        f'  <p class="meta">{date}{country_html} &middot; @{handle}</p>\n'
        f'  <p class="msg">{message}</p>\n'
        f'  <p class="cta">{" &middot; ".join(cta)}</p>\n'
        "</article>"
    )


def _facet_nav(facets):
    """Browse-by block. Present on every listing page so the hubs stay shallow."""
    if not facets:
        return ""
    blocks = []
    for label, entries in facets:
        if not entries:
            continue
        lis = "".join(
            f'<li><a href="{href}">{escape_html(name)}</a> <span style="color:var(--mut)">{n}</span></li>'
            for name, href, n in entries
        )
        blocks.append(f"<h2>{escape_html(label)}</h2>\n<ul>{lis}</ul>")
    if not blocks:
        return ""
    return '<div class="facets">\n' + "\n".join(blocks) + "\n</div>"


def _listing_page(*, title, description, canonical, h1, lead, articles, jsonld,
                  facet_nav="", pager="", prev_url=None, next_url=None, robots="index, follow"):
    rel = ""
    if prev_url:
        rel += f'\n    <link rel="prev" href="{prev_url}">'
    if next_url:
        rel += f'\n    <link rel="next" href="{next_url}">'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <!-- Vercel Web Analytics -->
    <script>
      window.va = window.va || function () {{ (window.vaq = window.vaq || []).push(arguments); }};
    </script>
    <script defer src="/_vercel/insights/script.js"></script>

    <title>{escape_html(title)}</title>
    <meta name="description" content="{escape_html(description)}">
    <meta name="robots" content="{robots}">
    <link rel="canonical" href="{canonical}">{rel}
    <meta property="og:title" content="{escape_html(title)}">
    <meta property="og:description" content="{escape_html(description)}">
    <meta property="og:type" content="website">
    <meta property="og:url" content="{canonical}">
    <meta property="og:site_name" content="PhD Sky">
    <meta property="og:image" content="{BASE_URL}assets/og-image.png">
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{escape_html(title)}">
    <meta name="twitter:description" content="{escape_html(description)}">
    <meta name="twitter:image" content="{BASE_URL}assets/og-image.png">
    <link rel="icon" type="image/svg+xml" href="/favicon.svg">
    <script type="application/ld+json">
{jsonld}
    </script>
    <style>{_LISTING_CSS}</style>
</head>
<body>
<div class="container">
    <a href="/" class="back-link">&larr; Back to the interactive board</a>
    <h1>{escape_html(h1)}</h1>
    <p class="subtitle">{lead}</p>
{facet_nav}
{articles}
{pager}
    <footer>
        <a href="/">Browse all PhD &amp; Postdoc positions</a> &middot;
        <a href="/positions">All positions</a> &middot;
        <a href="/about">About</a>
    </footer>
</div>
</body>
</html>"""


def _write_page(rel_path, html):
    path = os.path.join(DOCS_DIR, rel_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)


def _clean_orphans(subdir, keep):
    """Remove stale generated .html in `subdir` that this run didn't write."""
    d = os.path.join(DOCS_DIR, subdir)
    if not os.path.isdir(d):
        return 0
    removed = 0
    for fn in os.listdir(d):
        if fn.endswith(".html") and fn not in keep:
            os.remove(os.path.join(d, fn))
            removed += 1
    return removed


def build_facets(positions):
    """Discipline and country hubs, newest-first, skipping thin ones.

    Facets under FACET_MIN_POSITIONS are dropped rather than published: a hub
    with two entries is thin content that dilutes the good ones.
    """
    by_disc, by_country = {}, {}
    for pos in positions:
        for d in (pos.get("disciplines") or []):
            by_disc.setdefault(d, []).append(pos)
        c = pos.get("country")
        if c and c != "Unknown":
            by_country.setdefault(c, []).append(pos)

    def prep(mapping, kind):
        out = []
        for name, rows in mapping.items():
            slug = slugify(name)
            if not slug or len(rows) < FACET_MIN_POSITIONS:
                continue
            if kind == "area" and name in FACET_EXCLUDE_DISCIPLINES:
                continue
            out.append({
                "kind": kind, "name": name, "slug": slug,
                "rows": rows, "count": len(rows),
                "url": f"{BASE_URL}{kind}/{slug}",
                "href": f"/{kind}/{slug}",
            })
        return sorted(out, key=lambda f: -f["count"])

    return prep(by_disc, "area"), prep(by_country, "country")


def generate_facet_pages(disc_facets, country_facets, facet_nav):
    """Write /area/<slug> and /country/<slug> hub pages."""
    urls = []
    for facets, subdir in ((disc_facets, "area"), (country_facets, "country")):
        keep = set()
        for f in facets:
            rows = f["rows"][:FACET_MAX_ITEMS]
            # h1/title carry a literal '&'; _listing_page escapes them once.
            if f["kind"] == "area":
                h1 = f"{f['name']} PhD & Postdoc Positions"
                desc = (f"{f['count']} open {f['name']} PhD, postdoc and research positions "
                        f"aggregated from Bluesky. Updated daily.")
            else:
                h1 = f"PhD & Postdoc Positions in {f['name']}"
                desc = (f"{f['count']} open PhD, postdoc and research positions in "
                        f"{f['name']}, aggregated from Bluesky. Updated daily.")
            title = f"{h1} | PhD Sky"
            lead = (f"{f['count']} position{'s' if f['count'] != 1 else ''} &middot; "
                    f"showing the {len(rows)} most recent")
            html = _listing_page(
                title=title, description=desc, canonical=f["url"],
                h1=h1, lead=lead,
                articles="\n".join(_position_article(p) for p in rows),
                jsonld=json_for_script(
                    _collection_schema(title, desc, f["url"], rows), indent=2),
                facet_nav=facet_nav,
            )
            fn = f"{f['slug']}.html"
            _write_page(os.path.join(subdir, fn), html)
            keep.add(fn)
            urls.append(f["url"])
        _clean_orphans(subdir, keep)
    print(f"Generated facet hubs: {len(disc_facets)} area, {len(country_facets)} country")
    return urls


def generate_positions_html(positions, now=None):
    """Paginated /positions covering every active position."""
    positions = [p for p in positions if is_position_active(p, now=now)]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total = len(positions)
    pages = max(1, (total + POSITIONS_PER_PAGE - 1) // POSITIONS_PER_PAGE)

    disc_facets, country_facets = build_facets(positions)
    facet_nav = _facet_nav([
        ("Browse by research area", [(f["name"], f["href"], f["count"]) for f in disc_facets]),
        ("Browse by country", [(f["name"], f["href"], f["count"]) for f in country_facets]),
    ])

    def page_url(n):
        return BASE_URL + "positions" if n == 1 else f"{BASE_URL}positions/{n}"

    def page_href(n):
        return "/positions" if n == 1 else f"/positions/{n}"

    urls, keep = [], set()
    for n in range(1, pages + 1):
        rows = positions[(n - 1) * POSITIONS_PER_PAGE: n * POSITIONS_PER_PAGE]
        canonical = page_url(n)
        suffix = "" if n == 1 else f" &middot; page {n} of {pages}"
        title = ("All PhD & Postdoc Positions | PhD Sky" if n == 1
                 else f"All PhD & Postdoc Positions — page {n} of {pages} | PhD Sky")
        desc = (f"Current listing of {total} active PhD, postdoc and research positions "
                f"from academic sources. Updated daily.")

        nums = " ".join(
            f'<span class="cur">{i}</span>' if i == n else f'<a href="{page_href(i)}">{i}</a>'
            for i in range(1, pages + 1)
        )
        prev_html = f'<a href="{page_href(n - 1)}">&larr; Newer</a>' if n > 1 else "<span></span>"
        next_html = f'<a href="{page_href(n + 1)}">Older &rarr;</a>' if n < pages else "<span></span>"
        pager = (f'<nav class="pager"><div class="rel">{prev_html}{next_html}</div>'
                 f'<div class="nums">{nums}</div></nav>')

        html = _listing_page(
            title=title, description=desc, canonical=canonical,
            h1="PhD & Postdoc Positions",
            lead=f"{total} positions{suffix} &middot; last updated {today}",
            articles="\n".join(_position_article(p) for p in rows),
            jsonld=json_for_script(_collection_schema(title, desc, canonical, rows), indent=2),
            facet_nav=facet_nav,
            pager=pager,
            prev_url=page_url(n - 1) if n > 1 else None,
            next_url=page_url(n + 1) if n < pages else None,
            robots="index, follow" if n == 1 else "noindex, follow",
        )
        if n == 1:
            _write_page("positions.html", html)
        else:
            _write_page(os.path.join("positions", f"{n}.html"), html)
            keep.add(f"{n}.html")
        urls.append(canonical)

    _clean_orphans("positions", keep)
    facet_urls = generate_facet_pages(disc_facets, country_facets, facet_nav)
    print(f"Generated positions listing: {total} positions across {pages} pages")
    return urls + facet_urls


def render_position_page(pos, slug, now=None):
    """Render one usable detail page with truthful indexing and schema state."""
    canonical = f"{BASE_URL}p/{slug}"
    state = lifecycle_state(pos, now=now)
    eligible = state == "eligible"

    disciplines = pos.get("disciplines") or []
    types = pos.get("position_type") or []
    country = pos.get("country") or ""
    handle = pos.get("user_handle") or ""
    full_message = pos.get("message") or ""
    source_url = normalize_http_url(pos.get("url"))
    application_url = normalize_http_url(pos.get("application_url"))
    date = (pos.get("created_at") or "")[:10]

    fallback_title = " ".join([*(disciplines[:1] or ["Academic"]), *(types[:1] or ["position"])])
    job_title = (pos.get("job_title") or fallback_title).strip()
    employer = (pos.get("hiring_organization") or "").strip()
    location = (pos.get("location_text") or "").strip()
    page_title = f"{job_title} — {employer}" if employer else job_title
    with_location = f"{page_title} — {location}" if location else page_title
    if location and len(with_location) <= 65:
        page_title = with_location

    desc_source = " ".join(full_message.split())
    desc = desc_source[:155] + ("..." if len(desc_source) > 155 else "")
    robots = "index, follow" if eligible else "noindex, follow"

    jp = build_job_posting(pos, canonical_url=canonical) if eligible else None
    jp_script = ""
    if jp:
        jp_script = (
            '<script type="application/ld+json">'
            + json_for_script(jp, separators=(",", ":"))
            + "</script>"
        )

    tag_html = [f'<span class="tag">{escape_html(tag)}</span>' for tag in [*disciplines, *types]]
    if country and country != "Unknown":
        tag_html.append(f'<span class="tag">{escape_html(country)}</span>')

    handle_link = (
        f'<a href="https://bsky.app/profile/{escape_html(handle)}">@{escape_html(handle)}</a>'
        if handle else ""
    )

    notice = ""
    if state == "archived":
        notice = (
            '<div class="notice expired"><strong>This position is archived.</strong> '
            "Its stated deadline has passed or the source post is more than 90 days old. "
            "The page remains available as a reference.</div>"
        )
    elif state == "weak":
        notice = (
            '<div class="notice"><strong>Application details are incomplete.</strong> '
            "Check the source carefully before applying; this page is not included in search indexing.</div>"
        )

    deadline = effective_deadline(pos)
    details = []
    if employer:
        details.append(f"Hiring organization: {escape_html(employer)}")
    if location:
        details.append(f"Location: {escape_html(location)}")
    if deadline:
        details.append(f"Application deadline: {deadline.isoformat()}")
    details_html = "".join(f"<li>{item}</li>" for item in details)

    actions = []
    if state != "archived" and application_url:
        actions.append(
            f'<a class="cta primary" href="{escape_html(application_url)}" '
            'target="_blank" rel="noopener nofollow">Apply on the official site</a>'
        )
    if source_url:
        actions.append(
            f'<a class="cta secondary" href="{escape_html(source_url)}" '
            'target="_blank" rel="noopener nofollow">View source post</a>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>{escape_html(page_title)} | PhD Sky</title>
<meta name="description" content="{escape_html(desc)}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{escape_html(page_title)}">
<meta property="og:description" content="{escape_html(desc)}">
<meta property="og:type" content="article">
<meta property="og:url" content="{canonical}">
<meta property="og:site_name" content="PhD Sky">
<meta property="og:image" content="{BASE_URL}assets/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{escape_html(page_title)}">
<meta name="twitter:description" content="{escape_html(desc)}">
<meta name="twitter:image" content="{BASE_URL}assets/og-image.png">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
{jp_script}
<style>
  :root {{ --paper:#f3f5f2;--surface:#fff;--ink:#18201d;--muted:#55625c;--rule:#c8d0cb;--green:#18594a;--blue:#315f78;--red:#b54632; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0;background:var(--paper);color:var(--ink);font-family:Atkinson Hyperlegible,system-ui,sans-serif;line-height:1.65; }}
  .page {{ max-width:760px;margin:0 auto;padding:36px 18px 72px; }}
  .crumb {{ font-size:14px;margin-bottom:28px; }} .crumb a {{ color:var(--green); }}
  h1 {{ font-family:Literata,Georgia,serif;font-size:clamp(28px,5vw,42px);line-height:1.16;margin:0 0 12px; }}
  .citation {{ color:var(--muted);font-size:14px;margin:0 0 20px;padding-bottom:16px;border-bottom:3px solid var(--green); }}
  .citation a {{ color:var(--blue); }}
  .notice {{ background:var(--surface);border-left:4px solid var(--blue);padding:14px 16px;margin:20px 0; }}
  .notice.expired {{ border-left-color:var(--red); }}
  .facts {{ margin:18px 0;padding-left:22px;color:var(--muted); }}
  .tags {{ display:flex;flex-wrap:wrap;gap:6px;margin:18px 0 24px; }}
  .tag {{ border:1px solid var(--rule);background:var(--surface);padding:3px 8px;font-size:12px; }}
  .message {{ white-space:pre-wrap;background:var(--surface);border:1px solid var(--rule);padding:22px;margin:0 0 24px;overflow-wrap:anywhere; }}
  .actions {{ display:flex;flex-wrap:wrap;gap:10px; }}
  .cta {{ display:inline-flex;min-height:44px;align-items:center;padding:10px 16px;font-weight:700;text-decoration:none;border:2px solid var(--green); }}
  .cta.primary {{ background:var(--green);color:white; }} .cta.secondary {{ color:var(--green);background:transparent; }}
  .cta:hover {{ border-color:var(--red); }} :focus-visible {{ outline:3px solid var(--red);outline-offset:3px; }}
  footer {{ margin-top:48px;padding-top:20px;border-top:1px solid var(--rule);font-size:14px;color:var(--muted); }}
  footer a {{ color:var(--green); }}
</style>
</head>
<body>
<main class="page">
  <nav class="crumb" aria-label="Breadcrumb"><a href="/positions">&larr; Current positions</a></nav>
  <h1>{escape_html(job_title)}</h1>
  <p class="citation">Posted {date}{f" by {handle_link}" if handle_link else ""}</p>
  {notice}
  {f'<ul class="facts">{details_html}</ul>' if details_html else ''}
  <div class="tags">{"".join(tag_html)}</div>
  <div class="message">{escape_html(full_message)}</div>
  <div class="actions">{"".join(actions)}</div>
  <footer><a href="/">PhD Sky</a> &middot; <a href="/positions">Browse current positions</a></footer>
</main>
</body>
</html>
"""


def generate_position_pages(positions, now=None):
    """Write `docs/p/<slug>.html` for every canonical position; remove orphans."""
    pages_dir = os.path.join(DOCS_DIR, "p")
    os.makedirs(pages_dir, exist_ok=True)

    all_slugs = set()
    eligible_slug_to_lastmod = {}
    written = 0

    for pos in positions:
        slug = extract_slug(pos.get("uri"))
        if not slug:
            continue
        if slug in all_slugs:
            continue
        all_slugs.add(slug)
        if is_seo_eligible(pos, now=now):
            content_date = pos.get("seo_enriched_at") or pos.get("created_at") or ""
            eligible_slug_to_lastmod[slug] = content_date[:10]

        path = os.path.join(pages_dir, f"{slug}.html")
        html = render_position_page(pos, slug, now=now)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(html)
        written += 1

    removed = 0
    for filename in os.listdir(pages_dir):
        if not filename.endswith(".html"):
            continue
        if filename[:-5] not in all_slugs:
            os.remove(os.path.join(pages_dir, filename))
            removed += 1

    print(f"Generated per-job pages: {written} written, {removed} orphans cleaned")
    return eligible_slug_to_lastmod


def generate_sitemap(slug_to_lastmod=None, listing_urls=None):
    """Write a sitemap index plus separate core and eligible-job URL sets."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    def static_lastmod(filename):
        path = os.path.join(DOCS_DIR, filename)
        if not os.path.exists(path):
            return today
        return datetime.fromtimestamp(os.path.getmtime(path), timezone.utc).strftime("%Y-%m-%d")

    core_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"  <url><loc>{BASE_URL}</loc><lastmod>{today}</lastmod>"
        f"<changefreq>daily</changefreq><priority>1.0</priority></url>",
        f"  <url><loc>{BASE_URL}positions</loc><lastmod>{today}</lastmod>"
        f"<changefreq>daily</changefreq><priority>0.8</priority></url>",
        f"  <url><loc>{BASE_URL}about</loc><lastmod>{static_lastmod('about.html')}</lastmod>"
        f"<changefreq>monthly</changefreq><priority>0.4</priority></url>",
        f"  <url><loc>{BASE_URL}privacy</loc><lastmod>{static_lastmod('privacy.html')}</lastmod>"
        f"<changefreq>yearly</changefreq><priority>0.3</priority></url>",
        f"  <url><loc>{BASE_URL}terms</loc><lastmod>{static_lastmod('terms.html')}</lastmod>"
        f"<changefreq>yearly</changefreq><priority>0.3</priority></url>",
    ]

    # Only durable area/country hubs belong in the core sitemap. Pagination
    # remains crawlable through links but is intentionally noindex and omitted.
    listing = [
        u for u in (listing_urls or [])
        if "/area/" in u or "/country/" in u
    ]
    for url in listing:
        core_parts.append(
            f"  <url><loc>{url}</loc><lastmod>{today}</lastmod>"
            f"<changefreq>daily</changefreq><priority>0.7</priority></url>"
        )
    core_parts.append("</urlset>")

    job_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for slug in sorted(slug_to_lastmod or {}):
        lastmod = (slug_to_lastmod or {}).get(slug) or today
        job_parts.append(
            f"  <url><loc>{BASE_URL}p/{slug}</loc><lastmod>{lastmod}</lastmod>"
            f"<changefreq>weekly</changefreq><priority>0.6</priority></url>"
        )
    job_parts.append("</urlset>")

    sitemap_dir = os.path.join(DOCS_DIR, "sitemaps")
    os.makedirs(sitemap_dir, exist_ok=True)
    with open(os.path.join(sitemap_dir, "core.xml"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(core_parts))
    with open(os.path.join(sitemap_dir, "jobs.xml"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(job_parts))

    sitemap_index = "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"  <sitemap><loc>{BASE_URL}sitemaps/core.xml</loc><lastmod>{today}</lastmod></sitemap>",
        f"  <sitemap><loc>{BASE_URL}sitemaps/jobs.xml</loc><lastmod>{today}</lastmod></sitemap>",
        "</sitemapindex>",
    ])
    with open(os.path.join(DOCS_DIR, "sitemap.xml"), "w", encoding="utf-8", newline="\n") as f:
        f.write(sitemap_index)
    extra = len(slug_to_lastmod or {})
    print(f"Generated sitemap index: 5 core + {len(listing)} hubs + {extra} eligible jobs")


def _snapshot_position(pos):
    return {
        "uri": pos.get("uri", ""),
        "created_at": pos.get("created_at", ""),
        "disciplines": pos.get("disciplines") or [],
        "country": pos.get("country") or "",
        "position_type": pos.get("position_type") or [],
        "user_handle": pos.get("user_handle", ""),
        "message": pos.get("message", ""),
        "url": pos.get("url", ""),
        "is_verified_job": pos.get("is_verified_job") is True,
        "job_title": pos.get("job_title"),
        "hiring_organization": pos.get("hiring_organization"),
        "application_url": pos.get("application_url"),
        "application_deadline": (
            effective_deadline(pos).isoformat() if effective_deadline(pos) else None
        ),
        "location_text": pos.get("location_text"),
    }


def _snapshot_duplicate(row):
    return {
        "uri": row.get("uri", ""),
        "url": row.get("url", ""),
        "user_handle": row.get("user_handle", ""),
        "created_at": row.get("created_at", ""),
        "duplicate_of": row.get("duplicate_of", ""),
    }


def _write_snapshot(filename, positions, duplicates):
    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": len(positions),
        "positions": [_snapshot_position(pos) for pos in positions],
        "duplicates": [_snapshot_duplicate(row) for row in duplicates],
    }
    path = os.path.join(DOCS_DIR, filename)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(snapshot, f, separators=(",", ":"), ensure_ascii=False)
    size_kb = os.path.getsize(path) / 1024
    print(
        f"Generated {filename}: {len(positions)} positions, "
        f"{len(duplicates)} duplicates, {size_kb:.0f}KB"
    )


def generate_positions_json(positions, duplicates, now=None):
    """Write docs/positions.json — the active snapshot served from the CDN.

    Replaces the live Supabase query in docs/app.js. Schema matches what
    fetchSupabasePositions + fetchDuplicates produced, minus indexed_at
    (filtering already happened at generation time).
    """
    positions = [p for p in positions if is_position_active(p, now=now)]
    _write_snapshot("positions.json", positions, duplicates)


def generate_archive_json(positions, duplicates, now=None):
    """Write the lazy-loaded archive snapshot without changing SEO exposure."""
    positions = [p for p in positions if not is_position_active(p, now=now)]
    _write_snapshot("archive.json", positions, duplicates)


def report_generation_readiness(active_positions):
    """Report incomplete enrichment without blocking a safe partial refresh."""
    unenriched = [p for p in active_positions if not p.get("seo_enriched_at")]
    if unenriched:
        print(
            f"WARNING: {len(unenriched)} active positions have not completed SEO "
            "enrichment. They remain available in the feed but are excluded from "
            "the jobs sitemap and JobPosting markup until enriched."
        )
    return len(unenriched)


def main():
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("Fetching canonical positions from Supabase...")
    all_positions = fetch_all_canonical_positions(client)
    all_duplicates = fetch_all_duplicates(client)
    now = datetime.now(timezone.utc)
    active_positions = [p for p in all_positions if is_position_active(p, now=now)]
    report_generation_readiness(active_positions)
    eligible_count = sum(is_seo_eligible(p, now=now) for p in active_positions)
    active_uris = {p.get("uri") for p in active_positions}
    active_duplicates = [
        row for row in all_duplicates if row.get("duplicate_of") in active_uris
    ]
    archived_positions = [p for p in all_positions if not is_position_active(p, now=now)]
    archived_uris = {p.get("uri") for p in archived_positions}
    archived_duplicates = [
        row for row in all_duplicates if row.get("duplicate_of") in archived_uris
    ]
    print(
        f"Snapshot: {len(all_positions)} canonical; {len(active_positions)} active; "
        f"{eligible_count} SEO-eligible"
    )

    update_index_html(active_positions[:500], len(active_positions), now=now)
    listing_urls = generate_positions_html(active_positions, now=now)
    eligible_slug_to_lastmod = generate_position_pages(all_positions, now=now)
    generate_sitemap(eligible_slug_to_lastmod, listing_urls)
    generate_positions_json(active_positions, active_duplicates, now=now)
    generate_archive_json(archived_positions, archived_duplicates, now=now)

    print("SEO generation complete!")


if __name__ == "__main__":
    main()
