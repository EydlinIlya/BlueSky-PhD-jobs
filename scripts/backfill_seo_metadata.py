"""Resumably enrich active canonical positions with SEO job facts.

This is intentionally a metadata-only pass: it uses ``get_metadata`` once per
row and never repeats the real-job classification call.  Each successful row is
persisted immediately, so an interrupted run can be restarted safely.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from supabase import create_client

from src.llm.base import LLMUnavailableError
from src.llm.classifier import JobClassifier
from src.llm.config import MISTRAL_MODEL
from src.llm.mistral import MistralProvider
from src.seo import is_position_active


LOGGER = logging.getLogger("seo_backfill")
SELECT_FIELDS = (
    "uri,created_at,message,is_verified_job,duplicate_of,application_deadline,"
    "seo_enriched_at"
)
SEO_FIELDS = (
    "job_title",
    "hiring_organization",
    "application_url",
    "application_deadline",
    "location_text",
)


def fetch_candidates(client, page_size: int = 1000) -> list[dict]:
    """Fetch active, canonical, verified rows that have not been enriched."""
    rows = []
    offset = 0
    while True:
        response = (
            client.table("phd_positions")
            .select(SELECT_FIELDS)
            .eq("is_verified_job", True)
            .is_("duplicate_of", "null")
            .is_("seo_enriched_at", "null")
            .order("created_at", desc=True)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return [row for row in rows if is_position_active(row)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich active positions with evidence-backed SEO metadata."
    )
    parser.add_argument("--limit", type=int, default=0, help="Maximum rows; 0 means all")
    parser.add_argument("--model", default=MISTRAL_MODEL, help="Mistral model name")
    parser.add_argument(
        "--dry-run", action="store_true", help="Call the model but do not update Supabase"
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    args = parse_args()

    supabase_url = os.environ.get("SUPABASE_URL")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY")
    mistral_key = os.environ.get("MISTRAL_API_KEY")
    missing = [
        name
        for name, value in (
            ("SUPABASE_URL", supabase_url),
            ("SUPABASE_SERVICE_KEY", service_key),
            ("MISTRAL_API_KEY", mistral_key),
        )
        if not value
    ]
    if missing:
        raise SystemExit(f"Missing required environment variables: {', '.join(missing)}")

    client = create_client(supabase_url, service_key)
    provider = MistralProvider(mistral_key, model=args.model)
    classifier = JobClassifier(provider)

    candidates = fetch_candidates(client)
    if args.limit > 0:
        candidates = candidates[: args.limit]
    LOGGER.info("Found %s active, unenriched canonical positions", len(candidates))

    completed = 0
    for index, row in enumerate(candidates, 1):
        try:
            metadata = classifier.get_metadata(row.get("message") or "")
        except LLMUnavailableError:
            LOGGER.exception(
                "Mistral became unavailable at row %s/%s; completed rows are saved",
                index,
                len(candidates),
            )
            raise

        update = {field: metadata.get(field) for field in SEO_FIELDS}
        update["seo_enriched_at"] = datetime.now(timezone.utc).isoformat()
        if args.dry_run:
            LOGGER.info("[%s/%s] %s -> %s", index, len(candidates), row["uri"], update)
        else:
            client.table("phd_positions").update(update).eq("uri", row["uri"]).execute()
        completed += 1
        if completed % 25 == 0:
            LOGGER.info("Enriched %s/%s positions", completed, len(candidates))

    usage = provider.usage_totals
    LOGGER.info(
        "Complete: %s rows; prompt=%s cached=%s completion=%s tokens%s",
        completed,
        usage["prompt_tokens"],
        usage["cached_tokens"],
        usage["completion_tokens"],
        " (dry run)" if args.dry_run else "",
    )


if __name__ == "__main__":
    main()
