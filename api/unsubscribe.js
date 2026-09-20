"use strict";

// RFC 8058 endpoint for mailbox-provider one-click unsubscribe. Human-facing
// links use /unsubscribe and ask for confirmation before they POST here.
const DEFAULT_SUPABASE_URL = "https://qenpxgztlptegosdhhhi.supabase.co";
const DEFAULT_SUPABASE_ANON_KEY = "sb_publishable_149HAw6pWDQTRPF_NLISmA_oSCU7q3_";
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function requestToken(request) {
  const queryToken = request.query && request.query.token;
  if (Array.isArray(queryToken)) return queryToken[0] || "";
  if (typeof queryToken === "string") return queryToken;
  try {
    return new URL(request.url || "", "https://phdsky.org").searchParams.get("token") || "";
  } catch (_) {
    return "";
  }
}

async function handler(request, response) {
  response.setHeader("Cache-Control", "no-store");
  response.setHeader("Allow", "POST");

  // GET must never mutate state: link scanners routinely fetch every URL in an
  // email. Mailbox-provider one-click actions arrive as RFC 8058 POST requests.
  if (request.method !== "POST") {
    return response.status(405).json({ error: "Method not allowed" });
  }

  const token = requestToken(request);
  // Keep responses neutral so callers cannot use the endpoint to distinguish a
  // missing, invalid, previously used, or currently enabled token.
  if (!UUID_RE.test(token)) {
    return response.status(200).json({ ok: true });
  }

  const supabaseUrl = (process.env.SUPABASE_URL || DEFAULT_SUPABASE_URL).replace(/\/$/, "");
  const anonKey = process.env.SUPABASE_ANON_KEY || DEFAULT_SUPABASE_ANON_KEY;

  try {
    const rpcResponse = await fetch(`${supabaseUrl}/rest/v1/rpc/unsubscribe_by_token`, {
      method: "POST",
      headers: {
        apikey: anonKey,
        Authorization: `Bearer ${anonKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ p_token: token }),
    });
    if (!rpcResponse.ok) {
      console.error("unsubscribe RPC failed", rpcResponse.status);
      return response.status(503).json({ error: "Temporarily unavailable" });
    }
    return response.status(200).json({ ok: true });
  } catch (error) {
    console.error("unsubscribe request failed", error && error.message);
    return response.status(503).json({ error: "Temporarily unavailable" });
  }
}

module.exports = handler;
module.exports.requestToken = requestToken;
