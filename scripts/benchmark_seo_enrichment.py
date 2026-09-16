"""Benchmark the configured Ministral model on hand-reviewed SEO fixtures."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from src.llm.classifier import JobClassifier
from src.llm.config import MISTRAL_MODEL
from src.llm.mistral import MistralProvider


FIELDS = (
    "job_title",
    "hiring_organization",
    "application_url",
    "application_deadline",
    "location_text",
)


def normalized(value):
    return " ".join(value.split()).casefold() if isinstance(value, str) else value


def matches(actual, expected):
    """Allow a fixture to list multiple equally evidence-backed renderings."""
    if isinstance(expected, list):
        return any(normalized(actual) == normalized(candidate) for candidate in expected)
    return normalized(actual) == normalized(expected)


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture",
        default=str(Path(__file__).resolve().parent.parent / "tests/fixtures/seo_enrichment_cases.json"),
    )
    parser.add_argument("--model", default=MISTRAL_MODEL)
    parser.add_argument("--min-score", type=float, default=0.80)
    args = parser.parse_args()

    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise SystemExit("MISTRAL_API_KEY is required")

    cases = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
    provider = MistralProvider(api_key, model=args.model)
    classifier = JobClassifier(provider)
    correct = total = 0

    for case in cases:
        result = classifier.get_metadata(case["text"])
        failures = []
        for field in FIELDS:
            total += 1
            if matches(result.get(field), case["expected"].get(field)):
                correct += 1
            else:
                failures.append(
                    f"{field}: expected={case['expected'].get(field)!r} got={result.get(field)!r}"
                )
        print(f"{'PASS' if not failures else 'FAIL'} {case['name']}")
        for failure in failures:
            print(f"  {failure}")

    score = correct / total if total else 0
    usage = provider.usage_totals
    print(
        f"Score: {correct}/{total} ({score:.1%}); "
        f"prompt={usage['prompt_tokens']} cached={usage['cached_tokens']} "
        f"completion={usage['completion_tokens']}"
    )
    if score < args.min_score:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
