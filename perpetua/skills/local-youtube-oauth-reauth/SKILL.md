# YouTube OAuth Re-authorization

Re-run YouTube OAuth authorization for the `Mark Bobl | Karen vs AI` channel on a headless VM when the stored token is revoked or lost. The flow is semi-automated: the machine does everything, the user supplies one code.

## Confirm re-authorization is needed

- Treat `invalid_grant` on the refresh token, a lost token file, or 401s across all YouTube APIs (Data, Analytics, upload) as the trigger. Get the user's confirmation before starting.

- Read the existing client id and secret from `/home/hatch/data/youtube/.oauth.json` (600); never invent a new OAuth client for this channel.

- Keep the three scopes together: `youtube.upload`, `youtube.force-ssl`, and `yt-analytics.readonly`. A token missing any one of them fails part of the pipeline later.

## Generate the auth URL and collect the code

- Run `~/workspace/custom-skills/local-youtube-oauth-reauth/bin/gen_auth_url.py` to build the consent URL with `access_type=offline` and `prompt=consent`, so the exchange returns a refresh token.

- Send the URL to the user to open on their phone; they sign in as bat08738@gmail.com and approve.

- The redirect lands on `http://localhost:8080/?code=...` which will not load. Ask the user to copy the full address-bar URL back into chat and read the code from it.

## Exchange the code and verify

- Run `~/workspace/custom-skills/local-youtube-oauth-reauth/bin/exchange_code.py "<URL or code>"` to exchange the code, write `.oauth.json` (600), and run the verification checks.

- Confirm `channels.list(mine=true)` returns `Mark Bobl | Karen vs AI`, Analytics fields (`views`, `averageViewDuration`, `averageViewPercentage`, `shares`) read, and `commentThreads.list` reads.

- Confirm the MCP `youtube_upload` chain works without testing on a public video.

- After verification, restore the dependents one by one: upload chain, comment replies, post-publish optimizer, audits, and data-pull schedules.

## Keep the credential safe

- Never paste a token or secret into chat.

- Never send `.oauth.json` to another agent or machine. Keep each new authorization on this machine only; one revoked shared credential took every consumer down in the 2026-10-08 incident.

- Never skip `prompt=consent`; without it the exchange may return no refresh token.

## Available connectors

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.

## Alternatives for better results

- When only an external agent needs upload capability, point it at the MCP `youtube_upload` tool instead of re-authorizing locally; the token file never leaves this machine.

- Keep each new authorization on this machine only and never share it across machines or agents.