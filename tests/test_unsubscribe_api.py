"""Contract tests for the Vercel one-click unsubscribe endpoint."""

import json
import shutil
import subprocess

import pytest


NODE = shutil.which("node")


def _invoke(method: str, url: str) -> dict:
    script = r"""
const handler = require('./api/unsubscribe.js');
const result = {headers: {}, fetchCalls: []};
global.fetch = async (url, options) => {
  result.fetchCalls.push({url, method: options.method, body: options.body});
  return {ok: true, status: 200};
};
const request = {method: process.argv[1], url: process.argv[2], query: {}};
const response = {
  setHeader(name, value) { result.headers[name] = value; },
  status(code) { result.status = code; return this; },
  json(body) { result.body = body; return this; }
};
Promise.resolve(handler(request, response)).then(() => {
  process.stdout.write(JSON.stringify(result));
}).catch(error => {
  process.stderr.write(String(error));
  process.exit(1);
});
"""
    completed = subprocess.run(
        [NODE, "-e", script, method, url],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


@pytest.mark.skipif(NODE is None, reason="Node.js is required for Vercel function tests")
def test_get_is_a_noop_and_returns_405():
    result = _invoke(
        "GET",
        "/api/unsubscribe?token=4e162b33-229b-441a-b655-1fd560765037",
    )
    assert result["status"] == 405
    assert result["fetchCalls"] == []
    assert result["headers"]["Allow"] == "POST"


@pytest.mark.skipif(NODE is None, reason="Node.js is required for Vercel function tests")
def test_post_invokes_only_the_token_scoped_rpc():
    token = "4e162b33-229b-441a-b655-1fd560765037"
    result = _invoke("POST", f"/api/unsubscribe?token={token}")
    assert result["status"] == 200
    assert result["body"] == {"ok": True}
    assert len(result["fetchCalls"]) == 1
    call = result["fetchCalls"][0]
    assert call["url"].endswith("/rest/v1/rpc/unsubscribe_by_token")
    assert call["method"] == "POST"
    assert json.loads(call["body"]) == {"p_token": token}


@pytest.mark.skipif(NODE is None, reason="Node.js is required for Vercel function tests")
def test_invalid_token_returns_neutral_success_without_rpc():
    result = _invoke("POST", "/api/unsubscribe?token=not-a-token")
    assert result["status"] == 200
    assert result["body"] == {"ok": True}
    assert result["fetchCalls"] == []
