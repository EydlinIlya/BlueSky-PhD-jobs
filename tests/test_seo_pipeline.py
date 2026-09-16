"""Contract tests for carrying SEO metadata through source and publish rows."""

from src.pipeline.stages.publish import _staging_to_save_dict
from src.sources.base import Post


SEO_VALUES = {
    "job_title": "Postdoctoral Fellow in Coastal Ecology",
    "hiring_organization": "University of Haifa",
    "application_url": "https://jobs.example.edu/postings/123",
    "application_deadline": "2026-11-30",
    "location_text": "Haifa",
    "seo_enriched_at": "2026-09-16T10:00:00+00:00",
}


def test_post_to_dict_carries_all_seo_fields():
    post = Post(
        uri="at://did:plc:test/app.bsky.feed.post/abc",
        message="Detailed position description",
        url="https://bsky.app/profile/test/post/abc",
        user_handle="test.bsky.social",
        created_at="2026-09-16T09:00:00Z",
        source="bluesky",
        **SEO_VALUES,
    )
    row = post.to_dict()
    for field, value in SEO_VALUES.items():
        assert row[field] == value


def test_publish_mapping_carries_all_seo_fields():
    staging = {
        "uri": "at://did:plc:test/app.bsky.feed.post/abc",
        "message": "Detailed position description",
        "url": "https://bsky.app/profile/test/post/abc",
        "user_handle": "test.bsky.social",
        "created_at": "2026-09-16T09:00:00Z",
        "is_verified_job": True,
        **SEO_VALUES,
    }
    row = _staging_to_save_dict(staging)
    for field, value in SEO_VALUES.items():
        assert row[field] == value
