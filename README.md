<p><a href="https://phdsky.org/"><img src="docs/favicon.svg" alt="PhD Sky logo" width="80" height="80"></a></p>

# PhD Sky

Find PhD positions, postdoc jobs and other academic opportunities shared on
Bluesky, without having to follow every lab or catch every post.

**[Browse positions at phdsky.org](https://phdsky.org/)**

PhD Sky is a free, independent, non-commercial project operated by Eli Eydlin.
You can browse without an account. There are no paid listings or advertisements.

## Why this exists

A researcher announces an opening, colleagues share it, and the post soon slips
down the feed. Someone looking for that exact project might never see it.
PhD Sky collects those public announcements in one searchable place, so you can
look for opportunities by subject and country instead of relying on who you follow.

Bluesky has become a useful place for academic conversations and research sharing.
Its documented API also makes it practical for a small project to collect public
posts automatically. Our [Why Bluesky? page](https://phdsky.org/why-bluesky) explains
the choice, with links to academic studies, reporting and critical commentary.

## Find opportunities that fit

Search by keyword, filter by discipline, country or career stage, and open the
original announcement when something looks promising. You can hide posts from
known aggregator accounts if you prefer to browse other sources.

With an optional account, you can follow researchers and topics or save a search.
The Following feed brings those interests together. Saved searches can also send
weekly emails with new matches; you can edit, pause or unsubscribe from alerts.
Digest links point to PhD Sky position pages, where the original Bluesky post
and any available application link remain visible. Older listings remain
available in the archive.

## How it works

PhD Sky searches public Bluesky posts through its API. AI helps identify likely
vacancies and label them by subject, country and position type. When the source
supports it, the system also extracts the employer, application link and deadline.

It then groups repeated announcements so the same opening is easier to recognise.
The website links back to the original Bluesky post and includes an application
link when one is available. Collection runs several times a day, with a daily
website snapshot and separate email delivery.

These listings are collected automatically from Bluesky, not submitted directly
to PhD Sky by employers. You can read more about the process on the
[About page](https://phdsky.org/about).

## What to check before applying

Automation makes mistakes, and a social post rarely contains the whole vacancy.
Check funding, eligibility and deadlines with the hiring institution. PhD Sky
doesn't independently verify or endorse listings, and it doesn't cover every
academic opening. A PhD listing is not necessarily a funded PhD.

The current feed uses application deadlines where supported, otherwise a 90-day
posting window. That helps keep older posts out of the way, but it cannot guarantee
that a position is still open.

## Host your own version

Fork or clone this repository. With Python 3.11.9+ and a virtual environment, install
the collector with `pip install -e .`. Create a local `.env` file:

```dotenv
BLUESKY_HANDLE=your-handle.bsky.social
BLUESKY_PASSWORD=your-app-password
MISTRAL_API_KEY=your-mistral-api-key
```

```bash
python bluesky_search.py                         # Collect into a local CSV
python -m http.server --directory docs          # Preview the website
```

Open `http://localhost:8000/?mock` to try the interface with sample data. The CSV
run is separate from the website; it does not refresh the site's listings.

For a live instance, use your own Supabase database and authentication, apply the
SQL files in `migrations/` in numeric order, and set `SUPABASE_URL` and the
server-side `SUPABASE_KEY`. Collect with `--storage supabase`, then run
`python scripts/generate_seo_pages.py`. Deploy `docs/`; the included Vercel
configuration also supports the unsubscribe API. No frontend build step is needed.

Before deployment, replace the public Supabase settings and PhD Sky domain
references, including authentication redirects and email links. Never put service
keys in browser code. Configure your own GitHub Actions secrets before enabling
scheduled collection or email. See [AGENTS.md](AGENTS.md) for configuration,
architecture and testing details.

## Contribute or report a problem

Code, documentation and classification fixes are welcome through
[GitHub issues and pull requests](https://github.com/EydlinIlya/BlueSky-PhD-jobs).
To request correction or removal of your own public post, email
[eli.eydlin@gmail.com](mailto:eli.eydlin@gmail.com).

## License

The project code is licensed under [Apache 2.0](LICENSE). That license does not
grant rights to the third-party posts collected by the service.
