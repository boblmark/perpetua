# 浏览器问卷分段派发

## 拆成小批量

- 把问卷按最多 3 题一批拆分，每批派一个独立的浏览器任务。批量越小，单次掉线的损失越小。

- 内嵌每批全部题目的全文到任务文本里。浏览器读不到授予的文件，不内嵌就等于没问。

- 有依赖的题不要并行派。把前一批已得答案写进下一批的任务文本里，后题才能接着前题的结论问。

## 每题问完即落盘

- 在任务文本里明确要求：每拿到一题答案，先追加写入队列表文件，再问下一题。落盘先于汇报，不要等任务结束才写。

- 按下游捡答案路径能读的格式写答案。Ask Studio 评审就写进 /home/hatch/data/ask_studio/queue.json 的 answered 条目，答案正文写全，不要只写摘要。

- 告诉 worker 中途掉线是预期内的事。掉线前已落盘的答案全部有效，不需要重问。

## 只补问未答的题

- 先读队列表文件确认哪些题已有答案，再决定补问范围。已有答案的题一律不再重问。

- 补派任务只包含未答的题，重新按最多 3 题一批拆分。不要把整批原题重新派一遍。

- 只读不写队列表里已有答案的条目。不要刷新它的时间戳，不要重建它的问答记录。

## 把部分完成当部分成功

- 把掉线任务当部分成功处理。已落盘的答案照常进入下游，评审走捡答案，议会走收敛，只把未答的题重新排期。

- handoff 长时间不送达时 steer 一次让它直接输出结果。仍无结果就按队列表里的已落盘答案结算，缺失的题走补问，不要无限等待。

## Available connectors

- Use `muse.connector_search` to find other connectors and `muse.skill_search` to find related skills.

- If nothing here fits, look on the web for a maintained API or MCP server and set it up with [Custom Connectors and MCPs](/opt/muse/skills/custom-connector-setup/SKILL.md), or build a custom connector.

## Alternatives for better results

- 一两题的小问卷不用拆，直接走 [AI Brain Council](~/workspace/custom-skills/local-ai-brain-council/SKILL.md) 的单题配方。

- 落盘格式先对照捡答案代码的读取字段再定。字段名错位会导致答案已到但捡不到，先对齐再写。