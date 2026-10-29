# Browser Scheduled Upload Slot Check

## Create the slot check at upload

- Record the video id, the exact title, the scheduled slot with its timezone, and the visibility shown in Studio at upload time.

- Create a single scheduled check with `cron.add` at upload time and set it to run at the scheduled slot.

- Name the scheduled check with the video id and the scheduled slot so the slot run can find the upload record without searching.

- Do not rely on the pipeline private queue flipper for a browser upload, because a browser upload may never be written back to that queue.

- Treat the upload schedule approval as covering a rescue flip of the same video at the same slot, only when the title and description are unchanged and the user has not stopped the schedule.

## Check the slot and rescue a missed flip

- Check Studio visibility at the scheduled slot, not only at upload time.

- Compare the visibility shown in the list view with the visibility shown on the video detail page, and trust neither alone when they disagree.

- If the video is already public at the slot, close the scheduled check and report the public result.

- If the video is still private at the slot and the title and description are unchanged, flip that exact video to public under the upload schedule approval and change nothing else about its title or description.

- Read the video back after the rescue and confirm public visibility in both the list view and the detail page.

- Report the missed slot, the time it was found, and the rescue result immediately.

## Escalate when the rescue is not covered

- Stop and escalate immediately when the title or description changed, when the user stopped the schedule, or when you are unsure whether the schedule was approved.

- Do not flip a video in that case and do not wait for the next routine patrol.

- Record the reason the rescue was not covered so the next slot check can see the pattern.

## Available connectors

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.

## Websites

- [YouTube Studio](https://studio.youtube.com/) for uploading and scheduling videos. Carry the video id, the exact title, and the scheduled slot into the browser task and verify the visibility column and the video detail page there.

## Alternatives for better results

- Prefer the pipeline upload route when it is available, because it writes the queue entry the flipper reads.

- Use one slot check per video, at the slot, rather than repeated checks before the slot.

- Keep the scheduled slot unchanged during a rescue, unless the user approves a new slot.
