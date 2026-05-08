"""Generate SEO pages from Supabase data.

Produces:
- Embedded static JSON in docs/index.html (50 newest positions)
- <noscript> fallback with 30 positions as semantic HTML
- docs/positions.html - standalone static page with up to 500 positions + JSON-LD
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

    static_data = json.dumps(
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


def generate_positions_html(positions):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    articles = []
    for pos in positions[:500]:
        slug = extract_slug(pos.get("uri"))
        date = pos.get("created_at", "")[:10]
        country = pos.get("country") or ""
        country_html = f" | {escape_html(country)}" if country and country != "Unknown" else ""
        disciplines = pos.get("disciplines") or []
        disc_html = ", ".join(escape_html(d) for d in disciplines)
        types = pos.get("position_type") or []
        type_html = ", ".join(escape_html(t) for t in types)
        full_message = pos.get("message") or ""
        preview = full_message[:400] + ("..." if len(full_message) > 400 else "")
        message = escape_html(preview)
        handle = escape_html(pos.get("user_handle") or "")
        url = pos.get("url") or ""

        heading_inner = f"{disc_html} &mdash; {type_html}"
        heading = (
            f'<a href="/p/{slug}" style="color:#e2e8f0;text-decoration:none;">{heading_inner}</a>'
            if slug else heading_inner
        )

        cta_parts = []
        if slug:
            cta_parts.append(f'<a href="/p/{slug}" style="color:#6366f1;">Read more &rarr;</a>')
        if url:
            cta_parts.append(f'<a href="{escape_html(url)}" style="color:#94a3b8;">View on Bluesky</a>')
        cta_html = " &middot; ".join(cta_parts)

        articles.append(
            f'<article style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:1.5rem;margin-bottom:1rem;">\n'
            f'  <h2 style="font-size:1rem;margin:0 0 0.5rem 0;color:#e2e8f0;">{heading}</h2>\n'
            f'  <p style="font-size:0.85rem;color:#94a3b8;margin:0 0 0.75rem 0;">{date}{country_html} | @{handle}</p>\n'
            f'  <p style="font-size:0.95rem;line-height:1.6;color:#e2e8f0;margin:0 0 0.75rem 0;white-space:pre-wrap;">{message}</p>\n'
            f"  <p>{cta_html}</p>\n"
            f"</article>"
        )

    n = len(articles)
    dataset_schema = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "PhD & Postdoc Positions from Bluesky",
        "description": f"Complete listing of {n} PhD, postdoc, and research positions aggregated from Bluesky social network. AI-powered filtering updated daily.",
        "url": f"{BASE_URL}positions",
        "creator": {
            "@type": "Organization",
            "name": "BlueSky PhD Jobs",
            "url": BASE_URL,
        },
        "dateModified": today,
        "keywords": [
            "PhD positions", "postdoc jobs", "academic jobs",
            "research positions", "Bluesky", "university jobs",
            "doctoral research", "STEM careers",
        ],
        "isAccessibleForFree": True,
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "distribution": [{
            "@type": "DataDownload",
            "encodingFormat": "text/html",
            "contentUrl": f"{BASE_URL}positions",
        }],
    }
    jsonld = json.dumps(dataset_schema, indent=2)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>All PhD & Postdoc Positions | Academic Job Board</title>
    <meta name="description" content="Complete listing of PhD, postdoc, and research positions aggregated from Bluesky. Updated daily.">
    <meta name="keywords" content="PhD positions, postdoc jobs, academic jobs, research positions, Bluesky, university jobs, doctoral research, STEM careers">
    <meta name="author" content="BlueSky PhD Jobs">
    <meta name="robots" content="index, follow">
    <link rel="canonical" href="{BASE_URL}positions">
    <!-- Open Graph -->
    <meta property="og:title" content="All PhD & Postdoc Positions | Academic Job Board">
    <meta property="og:description" content="Complete listing of PhD, postdoc, and research positions aggregated from Bluesky. Updated daily.">
    <meta property="og:type" content="website">
    <meta property="og:url" content="{BASE_URL}positions">
    <meta property="og:site_name" content="BlueSky PhD Jobs">
    <meta property="og:image" content="{BASE_URL}assets/og-image.png">
    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="All PhD & Postdoc Positions | Academic Job Board">
    <meta name="twitter:description" content="Complete listing of PhD, postdoc, and research positions aggregated from Bluesky. Updated daily.">
    <meta name="twitter:image" content="{BASE_URL}assets/og-image.png">
    <!-- Dataset structured data -->
    <script type="application/ld+json">
{jsonld}
    </script>
    <style>
        body {{
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: #0f172a;
            color: #e2e8f0;
            margin: 0;
            padding: 2rem 1rem;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
        }}
        h1 {{
            font-size: 1.5rem;
            margin-bottom: 0.5rem;
        }}
        .subtitle {{
            color: #94a3b8;
            font-size: 0.9rem;
            margin-bottom: 2rem;
        }}
        a {{ color: #6366f1; }}
        a:hover {{ color: #10b981; }}
        .back-link {{
            display: inline-block;
            margin-bottom: 1.5rem;
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>
<div class="container">
    <a href="./" class="back-link">&larr; Back to interactive board</a>
    <h1>PhD &amp; Postdoc Positions</h1>
    <p class="subtitle">Showing {len(articles)} positions &middot; Last updated {today}</p>
{"".join(articles)}
    <p style="text-align:center;margin-top:2rem;">
        <a href="./">Browse all positions with filters &rarr;</a>
    </p>
</div>
</body>
</html>"""

    path = os.path.join(DOCS_DIR, "positions.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = len(html.encode("utf-8")) / 1024
    print(f"Generated positions.html: {len(articles)} positions, {size_kb:.0f}KB")


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
            + json.dumps(jp, separators=(",", ":"))
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


def generate_sitemap(slug_to_lastmod=None):
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
    print(f"Generated sitemap.xml: 2 + {extra} per-job URLs")


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
    generate_positions_html(positions)
    slug_to_lastmod = generate_position_pages(all_positions)
    generate_sitemap(slug_to_lastmod)
    generate_positions_json(all_positions, all_duplicates)

    print("SEO generation complete!")


if __name__ == "__main__":
    main()
