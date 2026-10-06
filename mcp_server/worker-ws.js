/**
 * Dash MCP 中继 Worker（WebSocket 版）
 *
 * 架构：
 *   Marvis -> POST /mcp -> Worker 经 WebSocket 转发给 poller -> 本地 MCP -> 原路返回
 *   poller  -> WSS /ws  (长连接，需 x-relay-secret 鉴权)
 *
 * 不再使用 KV 轮询，避免 KV 跨区复制延迟导致 waiter 看不到结果。
 *
 * 需要 Secrets：TOKEN（Marvis 的 Bearer token）、RELAY_SECRET（poller 用）
 * 注意：WebSocket 连接绑定到单个 Worker isolate，低流量下 /mcp 通常会命中同一 isolate。
 */

const TIMEOUT_MS = 25000;

function cors() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "authorization, content-type, mcp-session-id",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  };
}
function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...cors() },
  });
}

// 当前 poller 的 WebSocket 连接（单个 isolate 内有效）
let pollerWs = null;
// 待处理的请求：id -> { resolve, reject, timer }
const pending = new Map();

function sendToPoller(obj) {
  if (!pollerWs) return false;
  try {
    pollerWs.send(JSON.stringify(obj));
    return true;
  } catch {
    pollerWs = null;
    return false;
  }
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return new Response(null, { headers: cors() });

    // ---- poller 的 WebSocket 长连接 ----
    if (url.pathname === "/ws") {
      if (req.headers.get("Upgrade") !== "websocket") {
        return new Response("Expected websocket", { status: 400 });
      }
      const secret = url.searchParams.get("secret") || req.headers.get("x-relay-secret");
      if (secret !== env.RELAY_SECRET) {
        return new Response("unauthorized", { status: 401 });
      }
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      server.accept();

      // 替换旧连接
      if (pollerWs) { try { pollerWs.close(); } catch {} }
      pollerWs = server;
      console.log("poller ws connected");

      server.addEventListener("message", (event) => {
        let msg;
        try { msg = JSON.parse(event.data); } catch { return; }
        // 期望 { id, result } 或 { id, error }
        if (msg && msg.id !== undefined) {
          const p = pending.get(String(msg.id));
          if (p) {
            pending.delete(String(msg.id));
            clearTimeout(p.timer);
            p.resolve(msg);
          }
        }
      });
      const onClose = () => {
        if (pollerWs === server) pollerWs = null;
        // 清理该连接相关的 pending（全部超时失败）
        for (const [id, p] of pending) {
          clearTimeout(p.timer);
          pending.delete(id);
          p.reject(new Error("poller disconnected"));
        }
        console.log("poller ws closed");
      };
      server.addEventListener("close", onClose);
      server.addEventListener("error", onClose);

      return new Response(null, { status: 101, webSocket: client });
    }

    // ---- Marvis -> 中继：标准 MCP JSON-RPC ----
    if (url.pathname === "/mcp" && req.method === "POST") {
      if (req.headers.get("authorization") !== `Bearer ${env.TOKEN}`) {
        return json({ error: "unauthorized" }, 401);
      }
      let body;
      try { body = await req.json(); } catch { return json({ error: "bad json" }, 400); }
      const id = String(body.id ?? `n-${Date.now()}-${Math.floor(Math.random() * 1e6)}`);

      if (!pollerWs) {
        return json({ error: "poller not connected" }, 503);
      }

      let resultMsg;
      try {
        resultMsg = await new Promise((resolve, reject) => {
          const timer = setTimeout(() => {
            if (pending.has(id)) {
              pending.delete(id);
              reject(new Error("timeout waiting for dash backend"));
            }
          }, TIMEOUT_MS);
          pending.set(id, { resolve, reject, timer });
          if (!sendToPoller({ id, body })) {
            clearTimeout(timer);
            pending.delete(id);
            reject(new Error("poller not connected"));
          }
        });
      } catch (e) {
        return json({ error: e.message }, 504);
      }

      // resultMsg: { id, result } 或 { id, error }
      const payload = resultMsg.result !== undefined
        ? { jsonrpc: "2.0", id: body.id, result: resultMsg.result }
        : { jsonrpc: "2.0", id: body.id, error: resultMsg.error || { code: -32603, message: "backend error" } };
      return new Response(`data: ${JSON.stringify(payload)}\n\n`, {
        headers: { "Content-Type": "text/event-stream", ...cors() },
      });
    }

    if (url.pathname === "/health") {
      return json({ ok: true, relay: "dash-mcp-ws", poller: !!pollerWs });
    }
    return new Response("not found", { status: 404 });
  },
};
