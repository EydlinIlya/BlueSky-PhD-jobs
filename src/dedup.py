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


def mark_old_duplicates(
    new_posts: list[dict],
    storage,
    llm: LLMProvider | None = None,
) -> int:
    """Check new posts against existing canonical posts and mark old duplicates.

    For each new post that matches an existing canonical post, the old post
    gets `duplicate_of` set to the new post's URI (the new post becomes canonical).

    Args:
        new_posts: List of post dicts that were just saved
        storage: SupabaseStorage instance
        llm: Optional LLM provider for middle-zone verification

    Returns:
        Number of old posts marked as duplicates
    """
    # Only process Bluesky posts (have is_verified_job in dict)
    bluesky_new = [
        p for p in new_posts
        if p.get("is_verified_job") is True and p.get("uri", "").startswith("at://")
    ]
    if not bluesky_new:
        return 0

    # Fetch existing canonical posts, excluding the ones we just saved
    new_uris = {p["uri"] for p in bluesky_new}
    existing = [
        p for p in storage.get_posts_for_dedup()
        if p["uri"] not in new_uris
    ]
    if not existing:
        return 0

    # Preprocess all texts
    new_texts = [preprocess_text(p.get("message", "")) for p in bluesky_new]
    existing_texts = [preprocess_text(p["message"]) for p in existing]

    # Filter out empty texts
    valid_new = [(i, t) for i, t in enumerate(new_texts) if t]
    valid_existing = [(i, t) for i, t in enumerate(existing_texts) if t]
    if not valid_new or not valid_existing:
        return 0

    # Build TF-IDF matrix over all texts combined
    all_texts = [t for _, t in valid_existing] + [t for _, t in valid_new]
    n_existing = len(valid_existing)

    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2),
        stop_words="english",
        max_features=10000,
    )
    tfidf_matrix = vectorizer.fit_transform(all_texts)

    existing_matrix = tfidf_matrix[:n_existing]
    new_matrix = tfidf_matrix[n_existing:]

    # For each new post, find best match among existing
    marked_count = 0
    for new_idx, (orig_new_idx, _) in enumerate(valid_new):
        scores = cosine_similarity(new_matrix[new_idx:new_idx + 1], existing_matrix)[0]
        best_existing_idx = scores.argmax()
        best_score = float(scores[best_existing_idx])

        if best_score < LLM_THRESHOLD:
            continue

        orig_existing_idx = valid_existing[best_existing_idx][0]
        old_post = existing[orig_existing_idx]
        new_post = bluesky_new[orig_new_idx]

        is_duplicate = False
        if best_score >= AUTO_ACCEPT_THRESHOLD:
            is_duplicate = True
            logger.info(
                f"Auto-dedup (score={best_score:.3f}): "
                f"old={old_post['uri'][:50]}... → new={new_post['uri'][:50]}..."
            )
        elif llm:
            old_text = valid_existing[best_existing_idx][1]
            new_text = valid_new[new_idx][1]
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
