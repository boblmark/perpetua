# nanoMuse API 参考

Base URL: `http://127.0.0.1:18739` (local) / `https://nano.viralloopapp.com` (public)

Auth: `Authorization: Bearer <token>` (token in `/home/hatch/.nanomuse/server_token`)

## Threads

- `POST /api/threads` `{"title": "..."}` → `{"id": "t_xxx"}`
- `POST /api/threads/{id}/send` `{"text": "..."}` → event
- `GET /api/threads/{id}/events?limit=50` → `{"events": [...]}`

## State

- `GET /api/state` → settings, tools list, connections

## Event types

- `user`: user message
- `assistant`: agent response (`.text`)
- `tool`: tool call result (`.output`)
- `approval`: pending approval (`.status: "pending"`)
