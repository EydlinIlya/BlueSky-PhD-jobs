const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function sendJson(response, status, body, extraHeaders = {}) {
  response.statusCode = status;
  response.setHeader("Content-Type", "application/json; charset=utf-8");
  response.setHeader("Cache-Control", "no-store");
  Object.entries(extraHeaders).forEach(([name, value]) => response.setHeader(name, value));
  response.end(JSON.stringify(body));
}

function bodyValue(request, name) {
  if (request.body && typeof request.body === "object") return request.body[name];
  if (typeof request.body === "string") return new URLSearchParams(request.body).get(name);
  return null;
}

async function callRpc(name, token) {
  const baseUrl = process.env.SUPABASE_URL;
  const anonKey = process.env.SUPABASE_ANON_KEY;
  if (!baseUrl || !anonKey) throw new Error("Unsubscribe service is not configured");
  const response = await fetch(`${baseUrl.replace(/\/$/, "")}/rest/v1/rpc/${name}`, {
    method: "POST",
    headers: {
      apikey: anonKey,
      Authorization: `Bearer ${anonKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ p_token: token }),
  });
  if (!response.ok) throw new Error(`Unsubscribe RPC returned ${response.status}`);
  return response.json();
}

export default async function handler(request, response) {
  if (request.method !== "POST") {
    return sendJson(response, 405, { message: "Use POST to change email preferences." }, {
      Allow: "POST",
    });
  }

  const token = String(request.query.token || "");
  const scope = bodyValue(request, "scope");
  const isHumanConfirmation = scope === "current" || scope === "all";

  // RFC 8058 one-click requests receive a deliberately neutral response so
  // tokens cannot be probed. Human confirmation requests receive enough state
  // to show a friendly invalid/already-off message.
  if (!UUID_PATTERN.test(token)) {
    return sendJson(response, 200, isHumanConfirmation
      ? { ok: false, state: "not-found" }
      : { ok: true });
  }

  try {
    const rpcName = scope === "all"
      ? "unsubscribe_all_by_token"
      : "unsubscribe_subscription_by_token";
    const state = await callRpc(rpcName, token);
    return sendJson(response, 200, isHumanConfirmation
      ? { ok: state !== "not-found", state }
      : { ok: true });
  } catch (error) {
    console.error("unsubscribe failed", error instanceof Error ? error.message : error);
    return sendJson(response, isHumanConfirmation ? 503 : 200, isHumanConfirmation
      ? { ok: false, state: "error" }
      : { ok: true });
  }
}
