"""Generate SEO pages from Supabase data.

Produces:
- Embedded static JSON in docs/index.html (50 newest positions)
- <noscript> fallback with 30 positions as semantic HTML
- docs/positions.html + docs/positions/<n>.html - paginated listing of the FULL
  corpus, CollectionPage/ItemList JSON-LD. Pagination is what gives every
  per-job page an internal link; the sitemap alone leaves the tail orphaned.
- docs/area/<slug>.html, docs/country/<slug>.html - facet hubs. These are the
  real ranking targets ("Biology PhD positions in Germany" beats 214 separate
  38-word pages competing with each other).
- docs/p/<slug>.html - per-job pages carrying the JobPosting markup that makes
  the site eligible for Google Jobs
- docs/sitemap.xml
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client

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

JOB_VALID_DAYS = 90  # default expiry; academic posts rarely state one

# /positions listing. Paginated so every per-job page gets an internal link
# (the sitemap alone leaves the tail effectively orphaned).
POSITIONS_PER_PAGE = 200
# Facet hubs list only their most recent slice — they exist to rank and to pass
# links, not to mirror the whole corpus (pagination already covers that).
FACET_MAX_ITEMS = 200
FACET_MIN_POSITIONS = 5  # below this a hub is thin content; skip it
# Catch-all discipline labels that make meaningless landing pages — nobody
# searches "General call PhD positions". They stay as tags, just not as hubs.
FACET_EXCLUDE_DISCIPLINES = {"General call", "Other"}
LISTING_PREVIEW_CHARS = 300


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
    so the post ID lives in the trailing segment. ScholarshipDB URLs follow
    the same pattern. Sanitize defensively to keep it filename-safe.
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
    country = pos.get("country") or ""
    iso = COUNTRY_ISO.get(country)
    if not iso:
        return None

    created = pos.get("created_at") or ""
    if not created:
        return None

    disciplines = pos.get("disciplines") or []
    types = pos.get("position_type") or []
    if not disciplines or not types:
        return None

    title = f"{disciplines[0]} {types[0]}"
    employment_type = EMPLOYMENT_TYPE_MAP.get(types[0])

    handle = pos.get("user_handle") or ""
    description = pos.get("message") or ""
    fallback_url = pos.get("url") or ""
    listing_url = canonical_url or fallback_url

    try:
        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        valid_through = (dt + timedelta(days=JOB_VALID_DAYS)).isoformat()
    except ValueError:
        return None

    jp = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": title,
        "description": escape_html(description),
        "datePosted": created,
        "validThrough": valid_through,
        "employmentType": employment_type,
        "directApply": False,
        "url": listing_url,
        "hiringOrganization": {
            "@type": "Organization",
            "name": handle or "Bluesky poster",
            "sameAs": f"https://bsky.app/profile/{handle}" if handle else "",
        },
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": iso,
            },
        },
    }
    if not employment_type:
        jp.pop("employmentType")
    if not jp["hiringOrganization"]["sameAs"]:
        jp["hiringOrganization"].pop("sameAs")
    if not listing_url:
        jp.pop("url")
    return jp


def fetch_positions(client, limit=500):
    result = (
        client.table("phd_positions")
        .select("uri, created_at, disciplines, country, position_type, user_handle, message, url")
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
            .select("uri, created_at, disciplines, country, position_type, user_handle, message, url")
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
        disciplines = pos.get("disciplines") or []
        disc_html = ", ".join(escape_html(d) for d in disciplines)
        types = pos.get("position_type") or []
        type_html = ", ".join(escape_html(t) for t in types)
        message = escape_html((pos.get("message") or "")[:300])
        handle = escape_html(pos.get("user_handle") or "")
        url = pos.get("url") or ""

        heading = f"{disc_html} &mdash; {type_html}"
        if slug:
            heading = f'<a href="/p/{slug}">{heading}</a>'

        cta_parts = []
        if slug:
            cta_parts.append(f'<a href="/p/{slug}">Read more</a>')
        if url:
            cta_parts.append(f'<a href="{escape_html(url)}">View on Bluesky</a>')
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


def update_index_html(positions, total_count):
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

    with open(index_path, "w", encoding="utf-8") as f:
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
:root{--bg:#0f172a;--card:#1e293b;--bd:#334155;--fg:#e2e8f0;--mut:#94a3b8;--pri:#6366f1;--acc:#10b981}
*{box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--fg);margin:0;padding:2rem 1rem;line-height:1.55}
.container{max-width:820px;margin:0 auto}
h1{font-size:1.6rem;margin:0 0 .4rem}
.subtitle{color:var(--mut);font-size:.9rem;margin:0 0 1.5rem}
a{color:var(--pri)}a:hover{color:var(--acc)}
.back-link{display:inline-block;margin-bottom:1.25rem;font-size:.9rem}
.facets{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:1rem 1.25rem;margin-bottom:1.5rem}
.facets h2{font-size:.78rem;text-transform:uppercase;letter-spacing:.06em;color:var(--mut);margin:0 0 .5rem}
.facets ul{list-style:none;margin:0 0 1rem;padding:0;display:flex;flex-wrap:wrap;gap:.35rem .8rem}
.facets ul:last-child{margin-bottom:0}
.facets li{font-size:.85rem}
article{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:1.25rem;margin-bottom:1rem}
article h3{font-size:1rem;margin:0 0 .4rem}
article h3 a{color:var(--fg);text-decoration:none}
article h3 a:hover{color:var(--pri)}
.meta{font-size:.82rem;color:var(--mut);margin:0 0 .6rem}
.msg{font-size:.94rem;margin:0 0 .6rem;white-space:pre-wrap}
.cta{font-size:.85rem;margin:0}
nav.pager{margin:2rem 0 1rem;font-size:.9rem}
nav.pager .rel{display:flex;justify-content:space-between;gap:1rem;margin-bottom:.75rem}
nav.pager .nums{display:flex;flex-wrap:wrap;gap:.3rem .6rem;color:var(--mut);font-size:.85rem}
nav.pager .nums .cur{color:var(--fg);font-weight:600}
footer{margin-top:2rem;padding-top:1.25rem;border-top:1px solid var(--bd);font-size:.85rem;color:var(--mut)}
"""


def _position_article(pos):
    """One listing entry. Links to the per-job page, which holds JobPosting."""
    slug = extract_slug(pos.get("uri"))
    date = (pos.get("created_at") or "")[:10]
    country = pos.get("country") or ""
    country_html = f" &middot; {escape_html(country)}" if country and country != "Unknown" else ""
    disc_html = ", ".join(escape_html(d) for d in (pos.get("disciplines") or []))
    type_html = ", ".join(escape_html(t) for t in (pos.get("position_type") or []))
    full_message = pos.get("message") or ""
    preview = full_message[:LISTING_PREVIEW_CHARS] + (
        "..." if len(full_message) > LISTING_PREVIEW_CHARS else "")
    message = escape_html(preview)
    handle = escape_html(pos.get("user_handle") or "")
    url = pos.get("url") or ""

    heading_inner = f"{disc_html} &mdash; {type_html}" if disc_html or type_html else "Position"
    heading = f'<a href="/p/{slug}">{heading_inner}</a>' if slug else heading_inner

    cta = []
    if slug:
        cta.append(f'<a href="/p/{slug}">Read full posting &rarr;</a>')
    if url:
        cta.append(f'<a href="{escape_html(url)}" rel="nofollow">View on Bluesky</a>')

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
    with open(path, "w", encoding="utf-8") as f:
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


def generate_positions_html(positions):
    """Paginated /positions covering the WHOLE corpus.

    The old version listed only the newest 500, which left the rest of the
    per-job pages reachable from the sitemap alone. Sitemaps drive discovery;
    internal links drive crawl priority, so the tail was effectively orphaned.
    """
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
        desc = (f"Complete listing of {total} PhD, postdoc and research positions "
                f"aggregated from Bluesky. Updated daily.")

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


def render_position_page(pos, slug):
    """Render the standalone HTML page for a single position. Used by Google
    Jobs as the canonical landing URL — must surface the title, message, and
    a clear CTA back to the original Bluesky post.
    """
    canonical = f"{BASE_URL}p/{slug}"

    disciplines = pos.get("disciplines") or []
    types = pos.get("position_type") or []
    country = pos.get("country") or ""
    handle = pos.get("user_handle") or ""
    full_message = pos.get("message") or ""
    bsky_url = pos.get("url") or ""
    date = (pos.get("created_at") or "")[:10]

    disc_primary = disciplines[0] if disciplines else "Academic"
    type_primary = types[0] if types else "Position"
    country_part = f" — {country}" if country and country != "Unknown" else ""
    title = f"{disc_primary} {type_primary}{country_part}"

    desc_source = " ".join(full_message.split())
    desc = desc_source[:155] + ("..." if len(desc_source) > 155 else "")

    jp = build_job_posting(pos, canonical_url=canonical)
    jp_script = ""
    if jp:
        jp_script = (
            '<script type="application/ld+json">'
            + json_for_script(jp, separators=(",", ":"))
            + "</script>"
        )

    tag_html = []
    for d in disciplines:
        tag_html.append(f'<span class="tag tag-disc">{escape_html(d)}</span>')
    for t in types:
        tag_html.append(f'<span class="tag tag-pos">{escape_html(t)}</span>')
    if country and country != "Unknown":
        tag_html.append(f'<span class="tag tag-country">{escape_html(country)}</span>')

    handle_link = (
        f'<a href="https://bsky.app/profile/{escape_html(handle)}">@{escape_html(handle)}</a>'
        if handle else ""
    )

    cta = ""
    if bsky_url:
        cta = (
            f'<a class="cta" href="{escape_html(bsky_url)}" '
            f'target="_blank" rel="noopener">View original post on Bluesky &rarr;</a>'
        )

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

<title>{escape_html(title)} | PhD Sky</title>
<meta name="description" content="{escape_html(desc)}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{escape_html(title)}">
<meta property="og:description" content="{escape_html(desc)}">
<meta property="og:type" content="article">
<meta property="og:url" content="{canonical}">
<meta property="og:site_name" content="PhD Sky">
<meta property="og:image" content="{BASE_URL}assets/og-image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{escape_html(title)}">
<meta name="twitter:description" content="{escape_html(desc)}">
<meta name="twitter:image" content="{BASE_URL}assets/og-image.png">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<link rel="stylesheet" href="/design-tokens.css">
{jp_script}
<style>
  body {{ margin: 0; padding: 0; }}
  .page {{ max-width: 720px; margin: 0 auto; padding: 32px 16px 64px; }}
  .crumb {{ font-size: 13px; margin-bottom: 24px; font-family: var(--font-mono); }}
  .crumb a {{ color: var(--primary); text-decoration: none; }}
  .crumb a:hover {{ color: var(--accent); }}
  h1 {{ font-family: var(--font-mono); font-size: 28px; font-weight: 700;
        letter-spacing: -0.02em; line-height: 1.25; margin: 0 0 12px; color: var(--fg); }}
  .meta {{ color: var(--fg-subtle); font-family: var(--font-mono);
           font-size: 13px; margin: 0 0 16px; }}
  .meta a {{ color: var(--primary); }}
  .tags {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 24px; }}
  .tag {{ display: inline-block; padding: 3px 10px; border-radius: 4px;
          font-size: 12px; font-weight: 500; line-height: 1.5; color: white; }}
  .tag-pos {{ background: var(--pos-type-bg); }}
  .tag-country {{ background: var(--country-bg); }}
  .tag-disc {{ background: var(--bg-elevated); color: var(--fg-muted);
               border: 1px solid var(--border); }}
  .message {{ white-space: pre-wrap; line-height: 1.65; font-size: 15px;
              background: var(--bg-card); border: 1px solid var(--border);
              border-radius: var(--r-lg); padding: 20px; margin: 0 0 24px;
              word-wrap: break-word; overflow-wrap: anywhere; }}
  .cta {{ display: inline-flex; align-items: center; gap: 8px;
          padding: 12px 20px; background: var(--primary); color: white;
          text-decoration: none; border-radius: var(--r-md); font-weight: 600;
          font-size: 14px; transition: background var(--t-base); }}
  .cta:hover {{ background: var(--primary-hover); color: white; }}
  footer {{ margin-top: 48px; padding-top: 24px; border-top: 1px solid var(--border);
            font-size: 13px; color: var(--fg-subtle); font-family: var(--font-mono); }}
  footer a {{ color: var(--primary); }}
</style>
</head>
<body>
<div class="page">
  <nav class="crumb"><a href="/">&larr; All positions</a></nav>
  <h1>{escape_html(title)}</h1>
  <p class="meta">Posted {date}{f" by {handle_link}" if handle_link else ""}</p>
  <div class="tags">{"".join(tag_html)}</div>
  <div class="message">{escape_html(full_message)}</div>
  {cta}
  <footer>
    <a href="/">Browse all PhD &amp; Postdoc positions</a>
  </footer>
</div>
</body>
</html>
"""


def generate_position_pages(positions):
    """Write `docs/p/<slug>.html` for every canonical position; remove orphans."""
    pages_dir = os.path.join(DOCS_DIR, "p")
    os.makedirs(pages_dir, exist_ok=True)

    # slug -> created_at[:10], used by sitemap to set per-page lastmod so
    # Google doesn't recrawl 5k unchanged pages every cron run.
    slug_to_lastmod = {}
    written = 0

    for pos in positions:
        slug = extract_slug(pos.get("uri"))
        if not slug:
            continue
        if slug in slug_to_lastmod:
            continue
        slug_to_lastmod[slug] = (pos.get("created_at") or "")[:10]

        path = os.path.join(pages_dir, f"{slug}.html")
        html = render_position_page(pos, slug)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        written += 1

    removed = 0
    for filename in os.listdir(pages_dir):
        if not filename.endswith(".html"):
            continue
        if filename[:-5] not in slug_to_lastmod:
            os.remove(os.path.join(pages_dir, filename))
            removed += 1

    print(f"Generated per-job pages: {written} written, {removed} orphans cleaned")
    return slug_to_lastmod


def generate_sitemap(slug_to_lastmod=None, listing_urls=None):
    """Sitemap: static pages + paginated /positions + facet hubs + per-job pages.

    `listing_urls` are the listing/hub URLs returned by generate_positions_html.
    Page 1 of /positions is emitted from the static block, so it is filtered out
    of `listing_urls` to avoid a duplicate <loc>.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"  <url><loc>{BASE_URL}</loc><lastmod>{today}</lastmod>"
        f"<changefreq>daily</changefreq><priority>1.0</priority></url>",
        f"  <url><loc>{BASE_URL}positions</loc><lastmod>{today}</lastmod>"
        f"<changefreq>daily</changefreq><priority>0.8</priority></url>",
        f"  <url><loc>{BASE_URL}about</loc><lastmod>{today}</lastmod>"
        f"<changefreq>monthly</changefreq><priority>0.4</priority></url>",
        f"  <url><loc>{BASE_URL}privacy</loc><lastmod>{today}</lastmod>"
        f"<changefreq>yearly</changefreq><priority>0.3</priority></url>",
    ]

    listing = [u for u in (listing_urls or []) if u != f"{BASE_URL}positions"]
    for url in listing:
        # Facet hubs outrank paginated pages: they're the real ranking targets.
        priority = "0.7" if ("/area/" in url or "/country/" in url) else "0.5"
        parts.append(
            f"  <url><loc>{url}</loc><lastmod>{today}</lastmod>"
            f"<changefreq>daily</changefreq><priority>{priority}</priority></url>"
        )

    for slug in sorted(slug_to_lastmod or {}):
        lastmod = (slug_to_lastmod or {}).get(slug) or today
        parts.append(
            f"  <url><loc>{BASE_URL}p/{slug}</loc><lastmod>{lastmod}</lastmod>"
            f"<changefreq>weekly</changefreq><priority>0.6</priority></url>"
        )
    parts.append("</urlset>")
    xml = "\n".join(parts)

    path = os.path.join(DOCS_DIR, "sitemap.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    extra = len(slug_to_lastmod or {})
    print(f"Generated sitemap.xml: 4 static + {len(listing)} listing/hub + {extra} per-job URLs")


def generate_positions_json(positions, duplicates):
    """Write docs/positions.json — the static snapshot served from the CDN.

    Replaces the live Supabase query in docs/app.js. Schema matches what
    fetchSupabasePositions + fetchDuplicates produced, minus indexed_at
    (filtering already happened at generation time).
    """
    pos_payload = [
        {
            "uri": pos.get("uri", ""),
            "created_at": pos.get("created_at", ""),
            "disciplines": pos.get("disciplines") or [],
            "country": pos.get("country") or "",
            "position_type": pos.get("position_type") or [],
            "user_handle": pos.get("user_handle", ""),
            "message": pos.get("message", ""),
            "url": pos.get("url", ""),
        }
        for pos in positions
    ]

    dup_payload = [
        {
            "uri": d.get("uri", ""),
            "url": d.get("url", ""),
            "user_handle": d.get("user_handle", ""),
            "created_at": d.get("created_at", ""),
            "duplicate_of": d.get("duplicate_of", ""),
        }
        for d in duplicates
    ]

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "positions": pos_payload,
        "duplicates": dup_payload,
    }

    path = os.path.join(DOCS_DIR, "positions.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, separators=(",", ":"), ensure_ascii=False)
    size_kb = os.path.getsize(path) / 1024
    print(f"Generated positions.json: {len(pos_payload)} positions, {len(dup_payload)} duplicates, {size_kb:.0f}KB")


def main():
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("Fetching positions from Supabase...")
    positions = fetch_positions(client, limit=500)
    total_count = get_total_count(client)
    print(f"Fetched {len(positions)} positions for SEO (total canonical: {total_count})")

    if not positions:
        print("No positions found, skipping SEO generation")
        return

    print("Fetching full snapshot for static frontend data...")
    all_positions = fetch_all_canonical_positions(client)
    all_duplicates = fetch_all_duplicates(client)
    print(f"Snapshot: {len(all_positions)} canonical, {len(all_duplicates)} duplicates")

    update_index_html(positions, total_count)
    # The listing runs over the FULL corpus, not the newest 500 — pagination is
    # what gives every per-job page an internal link.
    listing_urls = generate_positions_html(all_positions)
    slug_to_lastmod = generate_position_pages(all_positions)
    generate_sitemap(slug_to_lastmod, listing_urls)
    generate_positions_json(all_positions, all_duplicates)

    print("SEO generation complete!")


if __name__ == "__main__":
    main()
