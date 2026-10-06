/**
 * Dash MCP 中继 Worker（部署到 Cloudflare Workers，免费版即可）
 *
 * Marvis（MCP 客户端） -> POST https://<你的worker>.workers.dev/mcp
 *        -> Worker 把 JSON-RPC 请求入队 KV -> 等待 20 秒
 * Dash 的 relay_poller.py 经代理轮询 -> 取走请求 -> 调本地 MCP server
 *        -> 把结果推回 KV -> Worker 返回给 Marvis
 *
 * 需要绑定：KV namespace，变量名 Q
 * 需要 Secrets：TOKEN（Marvis 的 Bearer token）、RELAY_SECRET（poller 用）
 */

const TIMEOUT_MS = 20000;

function cors() {
  return {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "authorization, content-type, mcp-session-id",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  };
}
function json(obj, status = 200, extra = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json", ...cors(), ...extra },
  });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 用单个 queue key 做任务队列：单 key 读写是强一致的，
// 比 Q.list()（最终一致、最多延迟约 60 秒）可靠得多。
async function readQueue(env) {
  try { return JSON.parse((await env.Q.get("queue")) || "[]"); }
  catch { return []; }
}
async function enqueue(env, id) {
  const q = await readQueue(env);
  if (!q.includes(id)) q.push(id);
  await env.Q.put("queue", JSON.stringify(q), { expirationTtl: 300 });
}
async function dequeue(env) {
  const q = await readQueue(env);
  const id = q.shift();
  await env.Q.put("queue", JSON.stringify(q), { expirationTtl: 300 });
  return id || null;
}
async function removeFromQueue(env, id) {
  const q = (await readQueue(env)).filter((x) => x !== id);
  await env.Q.put("queue", JSON.stringify(q), { expirationTtl: 300 });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return new Response(null, { headers: cors() });

    // ---- Marvis -> 中继：标准 MCP JSON-RPC ----
    if (url.pathname === "/mcp" && req.method === "POST") {
      if (req.headers.get("authorization") !== `Bearer ${env.TOKEN}`) {
        return json({ error: "unauthorized" }, 401);
      }
      let body;
      try { body = await req.json(); } catch { return json({ error: "bad json" }, 400); }
      const id = body.id ?? `n-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;
      await env.Q.put(`req:${id}`, JSON.stringify(body), { expirationTtl: 180 });
      await enqueue(env, id);
      const t0 = Date.now();
      while (Date.now() - t0 < TIMEOUT_MS) {
        const res = await env.Q.get(`res:${id}`);
        if (res !== null) {
          await env.Q.delete(`req:${id}`);
          await removeFromQueue(env, id);
          // 注意：不立即删除 res:id，靠 180s TTL 过期。
          // 若客户端重复投递导致多个 waiter 等同一个 id，删除会被第一个冒领，
          // 剩下的 waiter 永远等不到。保留 res 让重复的 waiter 也能拿到结果。
          return new Response(`data: ${res}\n\n`, {
            headers: { "Content-Type": "text/event-stream", ...cors() },
          });
        }
        await sleep(500);
      }
      await env.Q.delete(`req:${id}`);
      await removeFromQueue(env, id);
      return json({ error: "timeout waiting for dash backend" }, 504);
    }

    // ---- Dash poller 取任务 ----
    if (url.pathname === "/relay/pop" && req.method === "GET") {
      if (req.headers.get("x-relay-secret") !== env.RELAY_SECRET) {
        return json({ error: "unauthorized" }, 401);
      }
      const id = await dequeue(env);
      if (!id) return json({ empty: true });
      const raw = await env.Q.get(`req:${id}`);
      if (raw === null) return json({ empty: true });
      return json({ id, body: JSON.parse(raw) });
    }

    // ---- Dash poller 回结果 ----
    if (url.pathname === "/relay/push" && req.method === "POST") {
      if (req.headers.get("x-relay-secret") !== env.RELAY_SECRET) {
        return json({ error: "unauthorized" }, 401);
      }
      const { id, result } = await req.json();
      if (!id) return json({ error: "missing id" }, 400);
      await env.Q.put(`res:${id}`, JSON.stringify(result), { expirationTtl: 180 });
      return json({ ok: true });
    }

    if (url.pathname === "/health") return json({ ok: true, relay: "dash-mcp" });
    return new Response("not found", { status: 404 });
  },
};
