# Run one live Arena turn through the local bridge

## Gate the turn before you spend quota

- Check the quota warning before you start a turn and record its reset time, and start only when the warning allows a turn.

- Count the prompt characters locally and keep the prompt at or under 2500 characters, because the prompt box has no counter and rejects longer text.

- Take a fresh credential export for the turn and use it once within 20 minutes, because exported tokens expire in about 20 minutes.

- Import the export from a file and never hand copy the export text, because hand copying the export failed signature verification twice while file import verified and confirmed login.

- Confirm the bridge login state before you click Send, and treat a login box or a Terms popup covering Send as a login problem rather than a quota problem.

## Send once and verify the request actually left

- Click Send once and watch for the create-chat request, and treat the turn as sent only when that request leaves and a real session opens.

- Treat a run with only heartbeat traffic for about 110 seconds and a 120 second timeout as a bridge submit failure, not as proof that Arena or the account is down.

- Check that the session did not fall back to the all-zero address, because that address means no turn was created.

- Stop after one silent Send and move to diagnosis, because a second identical attempt wastes quota and time.

## Diagnose a silent Send once, then stop

- Take a screenshot and probe the Send button state and the page DOM after a silent Send, and record what covers Send and what the page actually shows.

- Do not retry the same turn in a headed browser after a headless attempt failed in the same way, because the headed probe on 2026-11-19 failed identically and ruled out the headless explanation.

- Do not seed localStorage with login state, because the localStorage explanation is unproven and the client does not use Supabase for that path.

- Ask the user to run the turn manually as a control when the bridge stays silent, because a manual turn that returns proves Arena and the account work and isolates the fault to the bridge.

## Restart the bridge without breaking it

- Pass the bridge proxy explicitly when you restart the bridge, because a restart without it leaves the browser without a proxy and the probe dies in seconds.

- Kill the real node process by its own PID and verify the port is free before you relaunch, because killing only the wrapper shell leaves the bridge running.

- Treat an address already in use error on the bridge port as a stale bridge process, and clear that exact process before you relaunch.

## Available connectors

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.

## Websites

- [Arena](https://arena.ai/video) for the live turn. Carry the full prompt text verbatim and verify after Send that a turn request was sent and a real session opened.

## Alternatives for better results

- Ask the user to run the same turn in their own browser as a control when the bridge Send stays silent, since a manual turn that returns proves the Arena path healthy and isolates the fault to the bridge.

- Wait for the quota reset time shown in the warning instead of spending another turn to probe exhaustion.

- Use a fresh export for the next attempt instead of reusing an export older than 20 minutes.
