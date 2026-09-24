"""Keep the static frontend's inlined aggregator set aligned with JSON."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_inlined_aggregators_match_json_source_of_truth():
    configured = set(json.loads(
        (ROOT / "docs" / "aggregators.json").read_text(encoding="utf-8")
    )["handles"])
    source = (ROOT / "docs" / "app.js").read_text(encoding="utf-8")
    match = re.search(
        r"const aggregatorHandles = new Set\(\[(.*?)\]\);", source, re.DOTALL
    )
    assert match, "app.js aggregator set was not found"
    inlined = set(re.findall(r'"([^"]+)"', match.group(1)))
    assert inlined == configured
