"""Benchmark Mistral models against the checked-in hand-labeled cases.

The benchmark uses the production ``JobClassifier`` and ``MistralProvider``.
It scores job filtering on every case and country/position extraction on real
jobs. Disciplines are retained in the report but are not scored because the
fixture does not yet have hand-reviewed discipline labels.

Usage:
    python scripts/benchmark_mistral_models.py
    python scripts/benchmark_mistral_models.py \
        --models ministral-14b-latest,mistral-small-latest
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import sys
import time

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.llm import JobClassifier, MistralProvider


FIXTURE = ROOT / "tests" / "fixtures" / "llm_benchmark_cases.json"
DEFAULT_MODELS = [
    "mistral-medium-latest",
    "mistral-small-latest",
    "ministral-14b-latest",
    "ministral-8b-latest",
]

# USD per million tokens from https://mistral.ai/pricing/api/ on 2026-09-16.
PRICES = {
    "mistral-medium-latest": {"input": 1.50, "output": 7.50},
    "mistral-small-latest": {"input": 0.15, "output": 0.60},
    "ministral-14b-latest": {"input": 0.20, "output": 0.20},
    "ministral-8b-latest": {"input": 0.15, "output": 0.15},
    "ministral-3b-latest": {"input": 0.10, "output": 0.10},
}

ALIASES = {
    "united kingdom": "uk",
    "england": "uk",
    "united states": "usa",
    "united states of america": "usa",
    "the netherlands": "netherlands",
    "holland": "netherlands",
    "phd position": "phd student",
    "phd candidate": "phd student",
    "doctoral researcher": "phd student",
    "doctoral research position": "phd student",
    "laboratory research assistant": "research assistant",
}


def normalize(value) -> str:
    normalized = str(value).lower().strip().rstrip(".")
    return ALIASES.get(normalized, normalized)


def position_matches(expected: str, predicted: list[str]) -> bool:
    if normalize(expected) == "multiple":
        return len(predicted) >= 2
    return any(normalize(value) == normalize(expected) for value in predicted)


def score(posts: list[dict]) -> dict:
    true_positive = sum(p["expected_job"] and p["predicted_job"] for p in posts)
    false_positive = sum(
        not p["expected_job"] and p["predicted_job"] for p in posts
    )
    true_negative = sum(
        not p["expected_job"] and not p["predicted_job"] for p in posts
    )
    false_negative = sum(
        p["expected_job"] and not p["predicted_job"] for p in posts
    )
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    precision = true_positive / precision_denominator if precision_denominator else 0.0
    recall = true_positive / recall_denominator if recall_denominator else 0.0
    f1_denominator = precision + recall
    f1 = 2 * precision * recall / f1_denominator if f1_denominator else 0.0
    real_jobs = [post for post in posts if post["expected_job"]]
    country_accuracy = (
        sum(p["country_ok"] for p in real_jobs) / len(real_jobs)
        if real_jobs
        else 0.0
    )
    position_accuracy = (
        sum(p["position_ok"] for p in real_jobs) / len(real_jobs)
        if real_jobs
        else 0.0
    )
    return {
        "filter_accuracy": (true_positive + true_negative) / len(posts),
        "filter_precision": precision,
        "filter_recall": recall,
        "filter_f1": f1,
        "confusion": {
            "tp": true_positive,
            "fp": false_positive,
            "tn": true_negative,
            "fn": false_negative,
        },
        "country_accuracy": country_accuracy,
        "position_accuracy": position_accuracy,
        "n_total": len(posts),
        "n_jobs": len(real_jobs),
    }


def estimated_cost(model: str, usage: dict) -> dict | None:
    price = PRICES.get(model)
    if not price:
        return None
    prompt = usage["prompt_tokens"]
    cached = usage["cached_tokens"]
    completion = usage["completion_tokens"]
    # Mistral bills cached prompt tokens at 10% of normal input price.
    standard = (
        ((prompt - cached) + cached * 0.1) * price["input"]
        + completion * price["output"]
    ) / 1_000_000
    return {
        "standard_usd": standard,
        "batch_usd": standard * 0.5,
        "price_usd_per_million": price,
    }


def run_model(model: str, cases: list[dict], api_key: str, workers: int) -> dict:
    provider = MistralProvider(api_key, model=model)
    classifier = JobClassifier(provider)
    records = [
        {
            "id": case["id"],
            "expected_job": case["expected"]["is_job"],
        }
        for case in cases
    ]
    latencies = []

    def filter_one(index: int):
        started = time.perf_counter()
        result = classifier.is_real_job(cases[index]["raw_text"])
        return index, result, time.perf_counter() - started

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(filter_one, i): i for i in range(len(cases))}
        for future in as_completed(futures):
            index, predicted, latency = future.result()
            records[index]["predicted_job"] = predicted
            latencies.append(latency)

    real_indices = [
        index for index, case in enumerate(cases) if case["expected"]["is_job"]
    ]

    def metadata_one(index: int):
        started = time.perf_counter()
        result = classifier.get_metadata(cases[index]["metadata_text"])
        return index, result, time.perf_counter() - started

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(metadata_one, i): i for i in real_indices}
        for future in as_completed(futures):
            index, metadata, latency = future.result()
            expected = cases[index]["expected"]
            records[index].update(
                predicted_country=metadata["country"],
                predicted_position=metadata["position_type"],
                predicted_disciplines=metadata["disciplines"],
                country_ok=normalize(metadata["country"])
                == normalize(expected["country"]),
                position_ok=position_matches(
                    expected["position"], metadata["position_type"]
                ),
            )
            latencies.append(latency)

    scores = score(records)
    usage = dict(provider.usage_totals)
    scores.update(
        usage=usage,
        cache_rate=(
            usage["cached_tokens"] / usage["prompt_tokens"]
            if usage["prompt_tokens"]
            else 0.0
        ),
        estimated_cost=estimated_cost(model, usage),
        latency_median_seconds=statistics.median(latencies),
        latency_mean_seconds=statistics.mean(latencies),
    )
    return {"scores": scores, "posts": records}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        parser.error("MISTRAL_API_KEY is required")

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = fixture["cases"]
    models = [model.strip() for model in args.models.split(",") if model.strip()]
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "fixture_version": fixture["version"],
        "label_policy": fixture["label_policy"],
        "models": {},
    }

    for model in models:
        print(f"Benchmarking {model}...", flush=True)
        started = time.perf_counter()
        result = run_model(model, cases, api_key, max(1, args.workers))
        result["scores"]["wall_time_seconds"] = time.perf_counter() - started
        report["models"][model] = result
        scores = result["scores"]
        print(
            f"  accuracy={scores['filter_accuracy']:.1%} "
            f"F1={scores['filter_f1']:.1%} "
            f"country={scores['country_accuracy']:.1%} "
            f"position={scores['position_accuracy']:.1%}",
            flush=True,
        )

    output = args.out or (
        ROOT
        / ".benchmarks"
        / f"mistral-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Saved {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
