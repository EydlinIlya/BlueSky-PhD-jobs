"""Behavior tests for the scanner-safe Vercel unsubscribe endpoint."""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VALID_TOKEN = "123e4567-e89b-42d3-a456-426614174000"

NODE_HARNESS = r"""
const fs = require("fs");

(async () => {
  const testCase = JSON.parse(process.argv[1]);
  const source = fs.readFileSync("api/unsubscribe.js", "utf8");
  const moduleUrl = "data:text/javascript;base64," + Buffer.from(source).toString("base64");
  const endpoint = await import(moduleUrl);

  process.env.SUPABASE_URL = "https://example.supabase.co";
  process.env.SUPABASE_ANON_KEY = "public-anon-key";

  const calls = [];
  global.fetch = async (url, options) => {
    calls.push({ url, options });
    if (testCase.rpcError) throw new Error("simulated network failure");
    return {
      ok: true,
      status: 200,
      json: async () => testCase.rpcState || "unsubscribed",
    };
  };

  const request = {
    method: testCase.method,
    query: { token: testCase.token || "" },
    body: testCase.body,
  };
  const response = {
    statusCode: 0,
    headers: {},
    setHeader(name, value) { this.headers[name] = value; },
    end(value) { this.body = value; },
  };

  await endpoint.default(request, response);
  process.stdout.write(JSON.stringify({
    status: response.statusCode,
    headers: response.headers,
    body: JSON.parse(response.body),
    calls,
  }));
})().catch((error) => {
  process.stderr.write(error.stack || String(error));
  process.exit(1);
});
"""


def invoke(**case):
    completed = subprocess.run(
        ["node", "-e", NODE_HARNESS, json.dumps(case)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_get_is_405_and_never_mutates():
    result = invoke(method="GET", token=VALID_TOKEN)
    assert result["status"] == 405
    assert result["headers"]["Allow"] == "POST"
    assert result["calls"] == []


def test_machine_post_is_neutral_for_invalid_and_reused_tokens():
    invalid = invoke(method="POST", token="not-a-token", body="List-Unsubscribe=One-Click")
    reused = invoke(
        method="POST",
        token=VALID_TOKEN,
        body="List-Unsubscribe=One-Click",
        rpcState="already-unsubscribed",
    )
    assert invalid["status"] == reused["status"] == 200
    assert invalid["body"] == reused["body"] == {"ok": True}
    assert invalid["calls"] == []
    assert "unsubscribe_subscription_by_token" in reused["calls"][0]["url"]


def test_human_confirmation_supports_one_alert_and_all_alerts():
    current = invoke(method="POST", token=VALID_TOKEN, body={"scope": "current"})
    all_alerts = invoke(
        method="POST",
        token=VALID_TOKEN,
        body={"scope": "all"},
        rpcState="already-unsubscribed",
    )
    assert current["body"] == {"ok": True, "state": "unsubscribed"}
    assert "unsubscribe_subscription_by_token" in current["calls"][0]["url"]
    assert all_alerts["body"] == {"ok": True, "state": "already-unsubscribed"}
    assert "unsubscribe_all_by_token" in all_alerts["calls"][0]["url"]


def test_machine_errors_are_neutral_but_human_errors_are_actionable():
    machine = invoke(
        method="POST",
        token=VALID_TOKEN,
        body="List-Unsubscribe=One-Click",
        rpcError=True,
    )
    human = invoke(
        method="POST",
        token=VALID_TOKEN,
        body={"scope": "current"},
        rpcError=True,
    )
    assert machine["status"] == 200 and machine["body"] == {"ok": True}
    assert human["status"] == 503 and human["body"] == {"ok": False, "state": "error"}
