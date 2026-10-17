

# nanoMuse Caller

## Purpose
Call the local nanoMuse instance (http://127.0.0.1:18739) from external programs, scripts, or other AI agents. nanoMuse has 29 tools including browser automation, code execution, web search, TTS, image/video generation, subagents, and cron.

Use this when:
- A Perpetua script needs AI assistance
- An external program wants to use nanoMuse's tools
- You need to bridge dispatcher jobs to nanoMuse

## Tooling
Helper CLI: `~/workspace/custom-skills/local-nanomuse-caller/bin/nano-call`

```bash
# Send a message and wait for response
nano-call "用 web_search 搜一下今天的 AI 新闻"

# With timeout (default 120s)
nano-call --timeout 300 "生成一张猫的图片" 

# Specify thread (reuses conversation context)
nano-call --thread t_abc123 "继续上一个任务"

# JSON output for programs
nano-call --json "查询日历明天的安排"
```

## Auth
The CLI reads the token from `/home/hatch/.nanomuse/server_token` automatically. No manual auth needed on the local machine.

For remote access, use the public URL `https://nano.viralloopapp.com/` with the token.

## Operating Rules
1. Keep prompts specific and actionable. nanoMuse works best with clear tool-oriented requests.
2. For long tasks (>5 min), the CLI polls automatically. Use `--timeout` to extend.
3. Video generation takes 10+ minutes. Use `--timeout 900`.
4. The CLI returns the agent's final response text. Tool outputs are included.
5. Do NOT use for Tier 3 operations (deleting data, revoking credentials, public uploads) without explicit user approval.

## References
- API details: `references/api.md`
- Tool list: `references/tools.md`
## Available connectors

Use `muse.connector_search` to find the current connector docs before following
recovered instructions.
