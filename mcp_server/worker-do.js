/**
 * Dash MCP 中继 Worker（Durable Object 版）
 *
 * 架构：
 *   Marvis -> POST /mcp -> 转发到 RelayHub DO -> 经 WebSocket 发给 poller -> 本地 MCP -> 原路返回
 *   poller  -> WSS /ws -> RelayHub DO (长连接，需 x-relay-secret 鉴权)
 *
 * Durable Object 保证单实例，WebSocket 和待处理请求都在同一实例内，无 isolate 问题。
 * 不再使用 KV 轮询。
 *
 * 需要 Secrets：TOKEN（Marvis 的 Bearer token）、RELAY_SECRET（poller 用）
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

// ---------- Durable Object：中继中心 ----------
// 注意：不要 extends DurableObject，Workers 里它不是全局变量
export class RelayHub {
  constructor(state, env) {
    this.state = state;
    this.env = env;
    this.ws = null;            // poller 的 WebSocket
    this.pending = new Map();  // id -> { resolve, reject, timer }
  }

  async fetch(req) {
    const url = new URL(req.url);

    // poller 的 WebSocket 长连接
    if (url.pathname === "/ws") {
      if (req.headers.get("Upgrade") !== "websocket") {
        return new Response("Expected websocket", { status: 400 });
      }
      const secret = url.searchParams.get("secret") || req.headers.get("x-relay-secret");
      if (secret !== this.env.RELAY_SECRET) {
        return new Response("unauthorized", { status: 401 });
      }
      const pair = new WebSocketPair();
      const [client, server] = Object.values(pair);
      server.accept();
      if (this.ws) { try { this.ws.close(); } catch {} }
      this.ws = server;

      server.addEventListener("message", (event) => {
        let msg;
        try { msg = JSON.parse(event.data); } catch { return; }
        if (msg && msg.id !== undefined) {
          const p = this.pending.get(String(msg.id));
          if (p) {
            this.pending.delete(String(msg.id));
            clearTimeout(p.timer);
            p.resolve(msg);
          }
        }
      });
      const onClose = () => {
        if (this.ws === server) this.ws = null;
        for (const [, p] of this.pending) {
          clearTimeout(p.timer);
          p.reject(new Error("poller disconnected"));
        }
        this.pending.clear();
      };
      server.addEventListener("close", onClose);
      server.addEventListener("error", onClose);
      return new Response(null, { status: 101, webSocket: client });
    }

    // Marvis 的 MCP 请求（由 Worker 转发过来，body 为 { id, body, token }）
    if (url.pathname === "/call" && req.method === "POST") {
      let msg;
      try { msg = await req.json(); } catch { return json({ error: "bad json" }, 400); }
      const id = String(msg.id);
      const rpcBody = msg.body;

      if (!this.ws) {
        return json({ error: "poller not connected" }, 503);
      }

      let resultMsg;
      try {
        resultMsg = await new Promise((resolve, reject) => {
          const timer = setTimeout(() => {
            if (this.pending.has(id)) {
              this.pending.delete(id);
              reject(new Error("timeout waiting for dash backend"));
            }
          }, TIMEOUT_MS);
          this.pending.set(id, { resolve, reject, timer });
          try {
            this.ws.send(JSON.stringify({ id, body: rpcBody }));
          } catch {
            clearTimeout(timer);
            this.pending.delete(id);
            reject(new Error("poller not connected"));
          }
        });
      } catch (e) {
        return json({ error: e.message }, 504);
      }

      const payload = resultMsg.result !== undefined
        ? { jsonrpc: "2.0", id: rpcBody.id, result: resultMsg.result }
        : { jsonrpc: "2.0", id: rpcBody.id, error: resultMsg.error || { code: -32603, message: "backend error" } };
      return json({ ok: true, payload });
    }

    if (url.pathname === "/status") {
      return json({ ok: true, poller: !!this.ws, pending: this.pending.size });
    }
    return new Response("not found", { status: 404 });
  }
}

// ---------- Worker 入口：鉴权 + 转发到 DO ----------
export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return new Response(null, { headers: cors() });

    // DO 未绑定时给明确提示，而不是 1101
    if (!env.HUB) {
      return json({ error: "durable object binding 'HUB' not configured" }, 500);
    }

    // 取单例 DO
    const id = env.HUB.idFromName("relay-hub");
    const hub = env.HUB.get(id);

    // poller WebSocket：直接转发到 DO
    if (url.pathname === "/ws") {
      return hub.fetch(req);
    }

    // Marvis MCP：鉴权后转发到 DO
    if (url.pathname === "/mcp" && req.method === "POST") {
      if (req.headers.get("authorization") !== `Bearer ${env.TOKEN}`) {
        return json({ error: "unauthorized" }, 401);
      }
      let body;
      try { body = await req.json(); } catch { return json({ error: "bad json" }, 400); }
      const callId = String(body.id ?? `n-${Date.now()}-${Math.floor(Math.random() * 1e6)}`);
      const doResp = await hub.fetch(new Request(new URL("/call", req.url).toString(), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: callId, body }),
      }));
      if (doResp.status === 503) return json({ error: "poller not connected" }, 503);
      if (doResp.status !== 200) {
        const t = await doResp.json().catch(() => ({}));
        return json({ error: t.error || "backend error" }, doResp.status === 504 ? 504 : 502);
      }
      const { payload } = await doResp.json();
      return new Response(`data: ${JSON.stringify(payload)}\n\n`, {
        headers: { "Content-Type": "text/event-stream", ...cors() },
      });
    }

    if (url.pathname === "/health") {
      // 问下 DO 的状态（不阻塞）
      let s = { poller: false };
      try {
        const r = await hub.fetch(new Request(new URL("/status", req.url).toString()));
        s = await r.json();
      } catch {}
      return json({ ok: true, relay: "dash-mcp-do", poller: s.poller });
    }
    return new Response("not found", { status: 404 });
  },
};
