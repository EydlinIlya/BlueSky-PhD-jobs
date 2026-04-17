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
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
# BASE_URL is the canonical public URL used in sitemap/JSON-LD. Set
# SITE_BASE_URL in the environment to override during/after the Vercel
# migration. Falls back to the current GitHub Pages URL so existing
# scheduled runs keep working unchanged.
BASE_URL = os.environ.get(
    "SITE_BASE_URL", "https://eydlinilya.github.io/BlueSky-PhD-jobs/"
)
if not BASE_URL.endswith("/"):
    BASE_URL += "/"
DOCS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")

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

        link_html = ""
        if url:
            link_html = f'<a href="{escape_html(url)}">View Post</a>'

        items.append(
            f"<article><h3>{disc_html} &mdash; {type_html}</h3>"
            f"<p><small>{date}{country_html} | @{handle}</small></p>"
            f"<p>{message}</p>"
            f"{link_html}</article>"
        )

    return (
        "<noscript>\n"
        '<div style="max-width:800px;margin:2rem auto;padding:0 1rem;color:#e2e8f0;">\n'
        "<h2>Recent PhD &amp; Postdoc Positions</h2>\n"
        + "\n".join(items)
        + '\n<p><a href="positions.html">View all positions</a></p>\n'
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
        date = pos.get("created_at", "")[:10]
        country = pos.get("country") or ""
        country_html = f" | {escape_html(country)}" if country and country != "Unknown" else ""
        disciplines = pos.get("disciplines") or []
        disc_html = ", ".join(escape_html(d) for d in disciplines)
        types = pos.get("position_type") or []
        type_html = ", ".join(escape_html(t) for t in types)
        message = escape_html(pos.get("message") or "")
        handle = escape_html(pos.get("user_handle") or "")
        url = pos.get("url") or ""

        link_html = ""
        if url:
            link_html = f'<p><a href="{escape_html(url)}" style="color:#6366f1;">View original post &rarr;</a></p>'

        articles.append(
            f'<article style="background:#1e293b;border:1px solid #334155;border-radius:8px;padding:1.5rem;margin-bottom:1rem;">\n'
            f'  <h2 style="font-size:1rem;margin:0 0 0.5rem 0;color:#e2e8f0;">{disc_html} &mdash; {type_html}</h2>\n'
            f'  <p style="font-size:0.85rem;color:#94a3b8;margin:0 0 0.75rem 0;">{date}{country_html} | @{handle}</p>\n'
            f'  <p style="font-size:0.95rem;line-height:1.6;color:#e2e8f0;margin:0 0 0.75rem 0;white-space:pre-wrap;">{message}</p>\n'
            f"  {link_html}\n"
            f"</article>"
        )

    n = len(articles)
    dataset_schema = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "PhD & Postdoc Positions from Bluesky",
        "description": f"Complete listing of {n} PhD, postdoc, and research positions aggregated from Bluesky social network. AI-powered filtering updated daily.",
        "url": f"{BASE_URL}positions.html",
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
            "contentUrl": f"{BASE_URL}positions.html",
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
    <link rel="canonical" href="{BASE_URL}positions.html">
    <!-- Open Graph -->
    <meta property="og:title" content="All PhD & Postdoc Positions | Academic Job Board">
    <meta property="og:description" content="Complete listing of PhD, postdoc, and research positions aggregated from Bluesky. Updated daily.">
    <meta property="og:type" content="website">
    <meta property="og:url" content="{BASE_URL}positions.html">
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


def generate_sitemap():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{BASE_URL}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{BASE_URL}positions.html</loc>
    <lastmod>{today}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>"""

    path = os.path.join(DOCS_DIR, "sitemap.xml")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    print("Generated sitemap.xml")


def main():
    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("Fetching positions from Supabase...")
    positions = fetch_positions(client, limit=500)
    total_count = get_total_count(client)
    print(f"Fetched {len(positions)} positions (total canonical: {total_count})")

    if not positions:
        print("No positions found, skipping SEO generation")
        return

    update_index_html(positions, total_count)
    generate_positions_html(positions)
    generate_sitemap()
    print("SEO generation complete!")


if __name__ == "__main__":
    main()
