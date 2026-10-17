# QC Gate Calibration

## Challenge thresholds with your own data

- Name the gate that is blocking output and the threshold it enforces, such as motion intensity at 3.0 or loop similarity at 0.75.

- Pull the channel's own retention data from Ask Studio in YouTube Studio, split by the gated attribute. Compare far shot openings against high motion openings on stayed to watch and swipe away.

- Let the data overrule the threshold. Ask Studio falsified a 3.0 motion threshold with first party data: far shot openings held 61 to 73 percent stayed against 45 percent for high motion openings.

- Record the falsification with the data source, the split, and the numbers. A threshold that loses to first party data gets recalibrated, not defended.

## Write exemptions as detectable specs

- Refuse fuzzy waivers. A red team kill stands on record: any slow opening will be retroactively relabeled as an establishing wide shot to dodge the check, so a waiver eats the rule.

- Write the exemption as a machine checkable alternative gate. Define entry conditions with measurable numbers, such as person box at most 15 percent of frame in the first 30 frames, monotonic approach, and static camera with background optical flow at most 0.8.

- Define the alternative check the video must pass instead, such as person region optical flow at least 2.0 between 1.5 and 3.0 seconds with person area growth of at least 25 percent.

- List the fail closed conditions. Any detection anomaly falls back to the original gate with no exception.

- Attach a validation window to every exemption. The council case used 180 days of logs. Kill any exemption the window does not sustain.

## Expire competitor formats

- Treat every competitor format source as perishable. A red team weaken stands: by the time a format is templatized, replicated, and through QC, the viral format has rotated.

- Mark any competitor source older than 30 days as stale. Do not feed stale formats into QC exemptions or replication.

## Available connectors

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.

## Alternatives for better results

- Run the four brain check before a gate enters the pipeline: Ask Studio diagnoses the bottleneck, LMArena judges the candidates, AI Studio writes the spec, the red team tries to kill it. A gate that survives is a constant, not a suggestion.

- When an exemption fails its validation window, remove it. Do not stack a second exemption on top of the first.
