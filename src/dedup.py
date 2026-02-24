"""Production deduplication: mark older duplicate posts when new ones arrive."""

import json
import logging
import re
import time

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.llm.base import LLMProvider

logger = logging.getLogger(__name__)

# Thresholds from experiment tuning
AUTO_ACCEPT_THRESHOLD = 0.95
LLM_THRESHOLD = 0.25

DUPLICATE_CHECK_PROMPT = """You are checking whether two academic job postings refer to the SAME position.

Two posts are duplicates if they advertise the same job at the same institution, even if worded differently.
Two posts are NOT duplicates if they are at different institutions, different departments, or different roles.

Respond with ONLY a JSON object:
{"duplicate": true/false, "confidence": 0.0-1.0, "reason": "brief explanation"}"""


def preprocess_text(message: str) -> str:
    """Clean post text for similarity comparison."""
    text = re.sub(r'^\[Bio:.*?\]\s*', '', message, flags=re.DOTALL)
    text = re.sub(r'\[Linked page -.*?\]', '', text, flags=re.DOTALL)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _verify_pair(llm: LLMProvider, text_a: str, text_b: str) -> bool:
    """Ask LLM whether two posts are duplicates."""
    text = (
        f"=== POST A ===\n{text_a}\n\n"
        f"=== POST B ===\n{text_b}\n"
    )
    try:
        response = llm.classify(text, DUPLICATE_CHECK_PROMPT).strip()
        response = re.sub(r'^```(?:json)?\s*', '', response)
        response = re.sub(r'\s*```$', '', response)
        data = json.loads(response)
        return bool(data.get("duplicate", False))
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning(f"LLM dedup parse error: {e}")
        return False


RECENT_WINDOW_DAYS = 3


def mark_old_duplicates(
    storage,
    llm: LLMProvider | None = None,
) -> int:
    """Compare recent posts against older canonical posts and mark old duplicates.

    Queries posts indexed in the last RECENT_WINDOW_DAYS from the database,
    so even if a previous run crashed, those posts will be picked up next time.

    For each recent post that matches an older canonical post, the older post
    gets `duplicate_of` set to the recent post's URI (newer = canonical).

    Returns:
        Number of old posts marked as duplicates
    """
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(days=RECENT_WINDOW_DAYS)).isoformat()
    recent = storage.get_canonical_posts(since=cutoff)
    if not recent:
        logger.info("Dedup: no recent posts to check")
        return 0

    older = storage.get_canonical_posts()
    # Exclude recent posts from the older set
    recent_uris = {p["uri"] for p in recent}
    older = [p for p in older if p["uri"] not in recent_uris]
    if not older:
        logger.info("Dedup: no older canonical posts to compare against")
        return 0

    logger.info(f"Dedup: comparing {len(recent)} recent posts against {len(older)} older posts")

    # Preprocess all texts
    recent_texts = [preprocess_text(p["message"]) for p in recent]
    older_texts = [preprocess_text(p["message"]) for p in older]

    # Filter out empty texts
    valid_recent = [(i, t) for i, t in enumerate(recent_texts) if t]
    valid_older = [(i, t) for i, t in enumerate(older_texts) if t]
    if not valid_recent or not valid_older:
        logger.info("Dedup: no valid texts after preprocessing, skipping")
        return 0

    # Build TF-IDF matrix over all texts combined
    all_texts = [t for _, t in valid_older] + [t for _, t in valid_recent]
    n_older = len(valid_older)

    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        stop_words="english",
        max_features=10000,
    )
    tfidf_matrix = vectorizer.fit_transform(all_texts)

    older_matrix = tfidf_matrix[:n_older]
    recent_matrix = tfidf_matrix[n_older:]

    # For each recent post, find best match among older posts
    marked_count = 0
    for rec_idx, (orig_rec_idx, _) in enumerate(valid_recent):
        scores = cosine_similarity(recent_matrix[rec_idx:rec_idx + 1], older_matrix)[0]
        best_older_idx = scores.argmax()
        best_score = float(scores[best_older_idx])

        new_post = recent[orig_rec_idx]
        logger.info(f"Dedup: post {new_post['uri'][:60]} best score={best_score:.3f}")

        if best_score < LLM_THRESHOLD:
            continue

        orig_older_idx = valid_older[best_older_idx][0]
        old_post = older[orig_older_idx]

        is_duplicate = False
        if best_score >= AUTO_ACCEPT_THRESHOLD:
            is_duplicate = True
            logger.info(
                f"Auto-dedup (score={best_score:.3f}): "
                f"old={old_post['uri'][:50]}... → new={new_post['uri'][:50]}..."
            )
        elif llm:
            old_text = valid_older[best_older_idx][1]
            new_text = valid_recent[rec_idx][1]
            is_duplicate = _verify_pair(llm, old_text, new_text)
            if is_duplicate:
                logger.info(
                    f"LLM-dedup (score={best_score:.3f}): "
                    f"old={old_post['uri'][:50]}... → new={new_post['uri'][:50]}..."
                )
            time.sleep(2)  # Rate limit

        if is_duplicate:
            storage.mark_duplicate(old_post["uri"], new_post["uri"])
            marked_count += 1

    if marked_count:
        logger.info(f"Marked {marked_count} old posts as duplicates of newer posts")

    return marked_count
