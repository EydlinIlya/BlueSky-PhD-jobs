"""Pre-save deduplication: filter duplicates before writing to storage."""

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


def _is_duplicate(score: float, llm, text_a: str, text_b: str) -> bool:
    """Check if a pair is duplicate based on score and optional LLM."""
    if score >= AUTO_ACCEPT_THRESHOLD:
        return True
    if score >= LLM_THRESHOLD and llm:
        result = _verify_pair(llm, text_a, text_b)
        time.sleep(2)  # Rate limit
        return result
    return False


def deduplicate_new_posts(
    new_posts: list[dict],
    storage,
    llm: LLMProvider | None = None,
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Deduplicate new posts before saving.

    Checks new posts against existing DB posts and against each other.
    Returns posts to save and duplicate relationships to record.

    Args:
        new_posts: Post dicts from the current fetch
        storage: SupabaseStorage instance
        llm: Optional LLM provider for middle-zone verification

    Returns:
        Tuple of:
        - posts_to_save: list of post dicts (canonical new + duplicates with duplicate_of set)
        - updates: list of (old_uri, canonical_uri) for existing DB posts to mark
    """
    if not new_posts:
        return [], []

    logger.info(f"Dedup: checking {len(new_posts)} new posts")

    # Fetch existing canonical posts from DB
    existing = storage.get_canonical_posts()
    logger.info(f"Dedup: {len(existing)} existing canonical posts in DB")

    # Preprocess all texts
    new_texts = [preprocess_text(p.get("message", "")) for p in new_posts]
    existing_texts = [preprocess_text(p.get("message", "")) for p in existing]

    # --- Phase 1: Dedup within the new batch ---
    # For pairs of new posts that are duplicates, keep the newest one
    duplicate_of_new = {}  # index -> index of canonical post in new_posts
    if len(new_posts) > 1:
        valid_new_batch = [(i, t) for i, t in enumerate(new_texts) if t]
        if len(valid_new_batch) > 1:
            batch_texts = [t for _, t in valid_new_batch]
            vectorizer = TfidfVectorizer(
                ngram_range=(1, 2), stop_words="english", max_features=10000,
            )
            batch_matrix = vectorizer.fit_transform(batch_texts)
            batch_sim = cosine_similarity(batch_matrix)

            # Process pairs: for each duplicate pair, the older post points to the newer
            for i in range(len(valid_new_batch)):
                if valid_new_batch[i][0] in duplicate_of_new:
                    continue  # already marked
                for j in range(i + 1, len(valid_new_batch)):
                    if valid_new_batch[j][0] in duplicate_of_new:
                        continue
                    score = float(batch_sim[i][j])
                    if score < LLM_THRESHOLD:
                        continue

                    orig_i = valid_new_batch[i][0]
                    orig_j = valid_new_batch[j][0]
                    text_i = batch_texts[i]
                    text_j = batch_texts[j]

                    if _is_duplicate(score, llm, text_i, text_j):
                        # Keep the newer post (later created_at) as canonical
                        post_i = new_posts[orig_i]
                        post_j = new_posts[orig_j]
                        ts_i = post_i.get("created", "")
                        ts_j = post_j.get("created", "")
                        if ts_i >= ts_j:
                            duplicate_of_new[orig_j] = orig_i
                            logger.info(
                                f"Batch-dedup (score={score:.3f}): "
                                f"{post_j['uri'][:50]} → {post_i['uri'][:50]}"
                            )
                        else:
                            duplicate_of_new[orig_i] = orig_j
                            logger.info(
                                f"Batch-dedup (score={score:.3f}): "
                                f"{post_i['uri'][:50]} → {post_j['uri'][:50]}"
                            )

        if duplicate_of_new:
            logger.info(f"Dedup: {len(duplicate_of_new)} duplicates within new batch")

    # --- Phase 2: Dedup new posts against existing DB posts ---
    # For each new canonical post that matches an existing post,
    # the older one gets marked as duplicate of the newer one
    db_updates = []  # (old_uri, canonical_uri) for existing posts to update

    canonical_new_indices = [
        i for i in range(len(new_posts)) if i not in duplicate_of_new
    ]
    if canonical_new_indices and existing_texts:
        valid_new = [(i, new_texts[i]) for i in canonical_new_indices if new_texts[i]]
        valid_existing = [(i, t) for i, t in enumerate(existing_texts) if t]

        if valid_new and valid_existing:
            all_texts = [t for _, t in valid_existing] + [t for _, t in valid_new]
            n_existing = len(valid_existing)

            vectorizer = TfidfVectorizer(
                ngram_range=(1, 2), stop_words="english", max_features=10000,
            )
            tfidf_matrix = vectorizer.fit_transform(all_texts)
            existing_matrix = tfidf_matrix[:n_existing]
            new_matrix = tfidf_matrix[n_existing:]

            for new_idx, (orig_new_idx, _) in enumerate(valid_new):
                scores = cosine_similarity(
                    new_matrix[new_idx:new_idx + 1], existing_matrix
                )[0]
                best_idx = scores.argmax()
                best_score = float(scores[best_idx])

                new_post = new_posts[orig_new_idx]
                logger.info(
                    f"Dedup: {new_post['uri'][:60]} vs DB best={best_score:.3f}"
                )

                if best_score < LLM_THRESHOLD:
                    continue

                orig_existing_idx = valid_existing[best_idx][0]
                old_post = existing[orig_existing_idx]
                old_text = valid_existing[best_idx][1]
                new_text = valid_new[new_idx][1]

                if _is_duplicate(best_score, llm, old_text, new_text):
                    # Newer post is canonical, older gets duplicate_of
                    new_ts = new_post.get("created", "")
                    old_ts = old_post.get("created_at", "")
                    if new_ts >= old_ts:
                        # New post is newer → mark old DB post
                        db_updates.append((old_post["uri"], new_post["uri"]))
                        logger.info(
                            f"DB-dedup (score={best_score:.3f}): "
                            f"old={old_post['uri'][:50]} → new={new_post['uri'][:50]}"
                        )
                    else:
                        # Existing post is newer → mark new post as duplicate
                        duplicate_of_new[orig_new_idx] = None  # special: points to DB post
                        new_post["duplicate_of"] = old_post["uri"]
                        logger.info(
                            f"DB-dedup (score={best_score:.3f}): "
                            f"new={new_post['uri'][:50]} → existing={old_post['uri'][:50]}"
                        )

    if db_updates:
        logger.info(f"Dedup: {len(db_updates)} existing DB posts to mark as duplicates")

    # --- Build final post list ---
    posts_to_save = []
    for i, post in enumerate(new_posts):
        if i in duplicate_of_new and duplicate_of_new[i] is not None:
            # Duplicate of another new post — set duplicate_of
            canonical_idx = duplicate_of_new[i]
            post = {**post, "duplicate_of": new_posts[canonical_idx]["uri"]}
        # If duplicate_of_new[i] is None, post already has duplicate_of set above
        posts_to_save.append(post)

    total_dupes = len(duplicate_of_new) + len(db_updates)
    if total_dupes:
        logger.info(f"Dedup: {total_dupes} total duplicates found")
    else:
        logger.info("Dedup: no duplicates found")

    return posts_to_save, db_updates
