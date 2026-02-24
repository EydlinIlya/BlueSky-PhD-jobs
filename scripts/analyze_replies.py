"""Analyze how many canonical verified-job posts in the DB are replies.

Saves reply-jobs to reply_jobs.json for manual review.
"""
import sys
import io
import json
import time

sys.path.insert(0, '.')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from src.storage.supabase import SupabaseStorage
from src.sources.bluesky import get_client

storage = SupabaseStorage()

# Only fetch canonical verified jobs from bluesky
all_posts = []
page_size = 1000
offset = 0
while True:
    resp = (storage.client.table('phd_positions')
        .select('uri, message, is_verified_job, duplicate_of, url')
        .like('uri', 'at://%')
        .eq('is_verified_job', True)
        .is_('duplicate_of', 'null')
        .range(offset, offset + page_size - 1)
        .execute())
    if not resp.data:
        break
    all_posts.extend(resp.data)
    if len(resp.data) < page_size:
        break
    offset += page_size

print(f'Total canonical verified jobs from Bluesky: {len(all_posts)}', flush=True)

client = get_client()

reply_jobs = []
errors = 0
checked = 0

for post_data in all_posts:
    uri = post_data['uri']
    try:
        thread = client.app.bsky.feed.get_post_thread({'uri': uri, 'depth': 0})
        record = thread.thread.post.record
        if getattr(record, 'reply', None) is not None:
            reply_jobs.append(post_data)
    except Exception as e:
        errors += 1
    checked += 1
    if checked % 200 == 0:
        print(f'Checked {checked}/{len(all_posts)}...', flush=True)
    time.sleep(0.15)

print(f'\nChecked: {checked}, Errors: {errors}', flush=True)
print(f'Replies among canonical verified jobs: {len(reply_jobs)}/{len(all_posts)}', flush=True)

# Save to file
with open('reply_jobs.json', 'w', encoding='utf-8') as f:
    json.dump(reply_jobs, f, ensure_ascii=False, indent=2)

print(f'\nSaved {len(reply_jobs)} reply-jobs to reply_jobs.json', flush=True)

# Print summary
for r in reply_jobs:
    msg = r['message'].replace('\n', ' ')[:200]
    print(f'\n{r["url"]}', flush=True)
    print(f'  {msg}', flush=True)
