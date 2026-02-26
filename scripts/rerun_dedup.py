"""One-time script to backup the database and re-run full deduplication.

Resets all duplicate_of values and re-applies dedup with the latest logic
(quote-URI, reply-based LLM, TF-IDF + LLM).

Usage:
    python -m scripts.rerun_dedup --dry-run   # preview changes
    python -m scripts.rerun_dedup              # apply changes
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

load_dotenv()

# Fix Windows console encoding
sys.stdout.reconfigure(encoding="utf-8")

from src.dedup import (
    AUTO_ACCEPT_THRESHOLD,
    LLM_THRESHOLD,
    preprocess_text,
    _verify_pair,
    _is_duplicate,
)
from src.llm import NvidiaProvider
from src.storage.supabase import SupabaseStorage


def fetch_all_rows(storage: SupabaseStorage) -> list[dict]:
    """Fetch ALL rows from phd_positions, paginated."""
    all_rows = []
    page_size = 1000
    offset = 0

    while True:
        response = (
            storage.client.table(storage.table)
            .select("*")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        if not response.data:
            break
        all_rows.extend(response.data)
        if len(response.data) < page_size:
            break
        offset += page_size

    return all_rows


def backup_database(rows: list[dict], output_dir: str = ".") -> str:
    """Save all rows to a timestamped JSON file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(output_dir, f"backup_phd_positions_{timestamp}.json")

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2, default=str)

    return filename


def reset_duplicate_of(storage: SupabaseStorage, dry_run: bool) -> int:
    """Set duplicate_of = NULL for every row that has one."""
    # Fetch URIs that currently have duplicate_of set
    all_duped = []
    offset = 0
    page_size = 1000

    while True:
        response = (
            storage.client.table(storage.table)
            .select("uri")
            .not_.is_("duplicate_of", "null")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        if not response.data:
            break
        all_duped.extend(response.data)
        if len(response.data) < page_size:
            break
        offset += page_size

    count = len(all_duped)
    if dry_run:
        print(f"  [DRY RUN] Would reset duplicate_of on {count} rows")
        return count

    # Batch update: clear duplicate_of for each URI
    for row in all_duped:
        storage.client.table(storage.table).update(
            {"duplicate_of": None}
        ).eq("uri", row["uri"]).execute()

    return count


def fetch_bluesky_metadata(
    bluesky_uris: list[str],
) -> dict[str, dict]:
    """Fetch quoted_uri and reply_parent_uri for Bluesky posts via AT Protocol API.

    Returns:
        Map of uri -> {"quoted_uri": str|None, "reply_parent_uri": str|None}
    """
    from src.sources.bluesky import get_client, extract_quote_post

    client = get_client()
    metadata = {}
    batch_size = 25

    for i in range(0, len(bluesky_uris), batch_size):
        batch = bluesky_uris[i : i + batch_size]
        try:
            response = client.app.bsky.feed.get_posts({"uris": batch})
            for post in response.posts:
                quoted = extract_quote_post(post)
                quoted_uri = quoted["uri"] if quoted and quoted.get("uri") else None

                reply_ref = getattr(post.record, "reply", None)
                reply_parent_uri = None
                if reply_ref:
                    parent = getattr(reply_ref, "parent", None)
                    if parent:
                        reply_parent_uri = getattr(parent, "uri", None)

                metadata[post.uri] = {
                    "quoted_uri": quoted_uri,
                    "reply_parent_uri": reply_parent_uri,
                }
        except Exception as e:
            print(f"  Warning: failed to fetch batch starting at index {i}: {e}")
            # Fill missing entries with empty metadata
            for uri in batch:
                if uri not in metadata:
                    metadata[uri] = {"quoted_uri": None, "reply_parent_uri": None}

        if i + batch_size < len(bluesky_uris):
            time.sleep(0.5)

    return metadata


def run_dedup(
    posts: list[dict],
    metadata: dict[str, dict],
    llm,
    dry_run: bool,
) -> list[tuple[str, str]]:
    """Run full dedup pipeline on all posts.

    Args:
        posts: All canonical posts (uri, message, created_at)
        metadata: Bluesky metadata map (uri -> {quoted_uri, reply_parent_uri})
        llm: LLM provider for verification
        dry_run: If True, don't modify anything

    Returns:
        List of (old_uri, canonical_uri) updates to apply
    """
    updates = []  # (old_uri, canonical_uri)
    marked = set()  # URIs already marked as duplicates

    uri_set = {p["uri"] for p in posts}
    uri_to_post = {p["uri"]: p for p in posts}

    # --- Phase 0a: Quote-URI dedup ---
    print("\n  Phase 0a: Quote-URI dedup...")
    quote_count = 0

    for post in posts:
        if post["uri"] in marked:
            continue
        meta = metadata.get(post["uri"], {})
        quoted_uri = meta.get("quoted_uri")
        if not quoted_uri or quoted_uri not in uri_set:
            continue
        # The quoting post is a duplicate of the quoted post
        quoted_post = uri_to_post[quoted_uri]
        if quoted_uri in marked:
            continue
        # Keep the quoted (original) post as canonical, mark the quoting post
        updates.append((post["uri"], quoted_uri))
        marked.add(post["uri"])
        quote_count += 1
        print(f"    Quote-dedup: {post['uri'][:60]} -> {quoted_uri[:60]}")

    print(f"  Phase 0a: {quote_count} quote-based duplicates")

    # --- Phase 0b: Reply-based LLM dedup ---
    print("\n  Phase 0b: Reply-based LLM dedup...")
    reply_count = 0

    for post in posts:
        if post["uri"] in marked:
            continue
        meta = metadata.get(post["uri"], {})
        parent_uri = meta.get("reply_parent_uri")
        if not parent_uri or parent_uri not in uri_set:
            continue
        parent_post = uri_to_post[parent_uri]
        if parent_uri in marked:
            continue

        reply_text = preprocess_text(post.get("message", ""))
        parent_text = preprocess_text(parent_post.get("message", ""))
        if not reply_text or not parent_text:
            continue

        if llm:
            is_dup = _verify_pair(llm, parent_text, reply_text)
            time.sleep(2)
            if is_dup:
                # Keep the newer post as canonical
                ts_reply = post.get("created_at", "")
                ts_parent = parent_post.get("created_at", "")
                if ts_reply >= ts_parent:
                    updates.append((parent_post["uri"], post["uri"]))
                    marked.add(parent_post["uri"])
                else:
                    updates.append((post["uri"], parent_post["uri"]))
                    marked.add(post["uri"])
                reply_count += 1
                print(f"    Reply-dedup: confirmed pair")
        else:
            print(f"    Reply-dedup: skipping (no LLM) - {post['uri'][:60]}")

    print(f"  Phase 0b: {reply_count} reply-based duplicates")

    # --- Phase 1: TF-IDF + LLM all-vs-all ---
    print("\n  Phase 1: TF-IDF + LLM all-vs-all dedup...")
    tfidf_count = 0

    # Build list of canonical (unmarked) posts
    canonical = [p for p in posts if p["uri"] not in marked]
    if len(canonical) < 2:
        print("  Phase 1: fewer than 2 canonical posts, skipping")
        return updates

    texts = [preprocess_text(p.get("message", "")) for p in canonical]
    valid_indices = [i for i, t in enumerate(texts) if t]

    if len(valid_indices) < 2:
        print("  Phase 1: fewer than 2 non-empty texts, skipping")
        return updates

    valid_texts = [texts[i] for i in valid_indices]
    valid_posts = [canonical[i] for i in valid_indices]

    print(f"  Building TF-IDF matrix for {len(valid_texts)} posts...")
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 2), stop_words="english", max_features=10000,
    )
    tfidf_matrix = vectorizer.fit_transform(valid_texts)

    # For each post, find its best match
    # Process in chunks to avoid memory issues with large similarity matrices
    chunk_size = 200
    for chunk_start in range(0, len(valid_posts), chunk_size):
        chunk_end = min(chunk_start + chunk_size, len(valid_posts))
        chunk_matrix = tfidf_matrix[chunk_start:chunk_end]
        sim = cosine_similarity(chunk_matrix, tfidf_matrix)

        for local_i in range(chunk_end - chunk_start):
            global_i = chunk_start + local_i
            post_i = valid_posts[global_i]
            if post_i["uri"] in marked:
                continue

            # Only check against posts with higher index to avoid duplicate pairs
            for j in range(global_i + 1, len(valid_posts)):
                post_j = valid_posts[j]
                if post_j["uri"] in marked:
                    continue

                score = float(sim[local_i][j])
                if score < LLM_THRESHOLD:
                    continue

                if _is_duplicate(score, llm, valid_texts[global_i], valid_texts[j]):
                    # Keep newer post as canonical
                    ts_i = post_i.get("created_at", "")
                    ts_j = post_j.get("created_at", "")
                    if ts_i >= ts_j:
                        updates.append((post_j["uri"], post_i["uri"]))
                        marked.add(post_j["uri"])
                    else:
                        updates.append((post_i["uri"], post_j["uri"]))
                        marked.add(post_i["uri"])
                    tfidf_count += 1
                    label = "auto" if score >= AUTO_ACCEPT_THRESHOLD else "llm"
                    print(
                        f"    TF-IDF-dedup ({label}, score={score:.3f}): "
                        f"{post_i['uri'][:40]}... vs {post_j['uri'][:40]}..."
                    )
                    break  # move to next post_i after finding a match

    print(f"  Phase 1: {tfidf_count} TF-IDF-based duplicates")

    return updates


def apply_updates(
    storage: SupabaseStorage,
    updates: list[tuple[str, str]],
    dry_run: bool,
) -> int:
    """Apply duplicate_of updates to the database."""
    if dry_run:
        print(f"\n  [DRY RUN] Would apply {len(updates)} duplicate_of updates")
        return len(updates)

    count = 0
    for old_uri, canonical_uri in updates:
        try:
            storage.client.table(storage.table).update(
                {"duplicate_of": canonical_uri}
            ).eq("uri", old_uri).execute()
            count += 1
        except Exception as e:
            print(f"  Error updating {old_uri[:60]}: {e}")

    return count


def main():
    parser = argparse.ArgumentParser(
        description="Backup database and re-run full deduplication"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying the database",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Skip the backup step (use if you already have a recent backup)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM verification (only auto-accept >= 0.95 and quote-URI dedup)",
    )
    args = parser.parse_args()

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"=== Re-run Dedup ({mode}) ===\n")

    # --- Step 1: Connect to Supabase ---
    print("Step 1: Connecting to Supabase...")
    storage = SupabaseStorage()
    print("  Connected.\n")

    # --- Step 2: Backup ---
    if not args.skip_backup:
        print("Step 2: Backing up database...")
        all_rows = fetch_all_rows(storage)
        print(f"  Fetched {len(all_rows)} rows")
        backup_file = backup_database(all_rows)
        print(f"  Saved to {backup_file}\n")
    else:
        print("Step 2: Skipping backup (--skip-backup)\n")

    # --- Step 3: Reset duplicate_of ---
    print("Step 3: Resetting all duplicate_of values...")
    reset_count = reset_duplicate_of(storage, args.dry_run)
    print(f"  Reset {reset_count} rows\n")

    # --- Step 4: Fetch canonical posts ---
    print("Step 4: Fetching all canonical posts...")
    if args.dry_run:
        # In dry-run, duplicate_of wasn't actually cleared, so fetch all verified posts
        all_posts = []
        offset = 0
        page_size = 1000
        while True:
            response = (
                storage.client.table(storage.table)
                .select("uri, message, created_at")
                .eq("is_verified_job", True)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            if not response.data:
                break
            all_posts.extend(response.data)
            if len(response.data) < page_size:
                break
            offset += page_size
    else:
        # After reset, all verified posts are canonical
        all_posts = storage.get_canonical_posts()

    print(f"  {len(all_posts)} verified posts to process\n")

    # --- Step 5: Fetch Bluesky metadata ---
    print("Step 5: Fetching Bluesky post metadata (quote/reply info)...")
    bluesky_uris = [p["uri"] for p in all_posts if p["uri"].startswith("at://")]
    non_bluesky = len(all_posts) - len(bluesky_uris)
    print(f"  {len(bluesky_uris)} Bluesky posts, {non_bluesky} non-Bluesky posts")

    if bluesky_uris:
        metadata = fetch_bluesky_metadata(bluesky_uris)
        print(f"  Fetched metadata for {len(metadata)} posts")

        has_quote = sum(1 for m in metadata.values() if m.get("quoted_uri"))
        has_reply = sum(1 for m in metadata.values() if m.get("reply_parent_uri"))
        print(f"  {has_quote} with quoted_uri, {has_reply} with reply_parent_uri")
    else:
        metadata = {}
    print()

    # --- Step 6: Set up LLM ---
    llm = None
    if not args.no_llm:
        api_key = os.environ.get("NVIDIA_API_KEY")
        if api_key:
            llm = NvidiaProvider(api_key)
            print("LLM provider: NVIDIA (enabled)")
        else:
            print("LLM provider: None (no NVIDIA_API_KEY)")
    else:
        print("LLM provider: disabled (--no-llm)")
    print()

    # --- Step 6: Run dedup ---
    print("Step 6: Running deduplication...")
    updates = run_dedup(all_posts, metadata, llm, args.dry_run)

    # --- Step 7: Apply updates ---
    print(f"\nStep 7: Applying {len(updates)} updates...")
    applied = apply_updates(storage, updates, args.dry_run)

    # --- Summary ---
    print(f"\n{'='*40}")
    print(f"Summary ({mode}):")
    print(f"  Total posts processed: {len(all_posts)}")
    print(f"  Duplicates found: {len(updates)}")
    print(f"  Updates applied: {applied}")
    print(f"  Canonical posts remaining: {len(all_posts) - len(updates)}")
    print(f"{'='*40}")


if __name__ == "__main__":
    main()
