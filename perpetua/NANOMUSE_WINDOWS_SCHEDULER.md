# nanoMuse Windows 调度器架构方案

> 目标：在新 Windows VPS 上部署 nanoMuse，接管目前跑在 Muse 平台调度器上的
> 92 个 agent 定时任务；Linux 本机逐步退到开发/备份。
> 用户决策：方案 (a)（2026-10-16）。本文档 2026-10-16 起草。

---

## 1. 现状调研（Linux 侧已有什么）

### 1.1 两套调度机制并存

```
Muse 平台（现状生产）                     nanoMuse（热备/影子）
─────────────────────                     ────────────────────
平台 cron 到点 → spawn worker agent         本机 APScheduler → 抢租约(SQLite)
   （92 agent 任务 + 21 直接命令             → 简单任务 subprocess 直跑
     + 5 未解析 = 118 定义）                  → 复杂任务调 API 开线程推理
   调度器在平台层                            （hydrate_and_run，见 1.3）
```

### 1.2 nanoMuse 调度器已落地（/home/hatch/data/nanomuse-migration/scheduler/）

| 组件 | 文件 | 状态 |
|---|---|---|
| 调度器本体 | `scheduler.py`（313 行，APScheduler + SQLAlchemyJobStore） | ✅ 可用 |
| cron→jobs.yaml 转换器 | `cron_convert.py`（81 Muse cron） | ✅ 可用 |
| 任务清单 | `jobs.yaml`（77：shadow 7 / full 44 / manual 26） | ✅ 运行中 |
| 单写者租约 | `ownership.db`（SQLite，writer ∈ muse/nanomuse/none） | ✅ 10 条已登记 |
| 执行门 | `_execution_decision()`：manual 永不执行 / shadow 仅只读白名单 / full 仅 writer=nanomuse | ✅ M1 已修 |
| 模型路由 | `model_router.py`（agnes-2.5-flash=fast / gemini-auto=powerful / local-gemma-4-26b） | ✅ BYOK 已接 |
| Agent 执行 | `agent_context.py::hydrate_and_run`（headless MuseAgent + 受限工具集） | ⚠️ 已实现但**未接入**调度器 |

### 1.3 关键 Gap（本次要补的）

1. **`hydrate_and_run` 未接线**：`scheduler.run_shadow_job` 目前只 `subprocess.run(command)`；
   全 repo 无调用方。92 个 agent 任务的 .md 正文是自然语言指令（含判断逻辑），
   必须走 agent 执行，不能只跑抽出的 shell 命令。
2. **路径硬编码**：`BASE=/home/hatch/data/nanomuse-migration`、
   `CRON_WORKSPACE=/home/hatch/data/perpetua`、`LLM_ASSETS=/home/hatch/data/llm_assets`
   散落在 scheduler.py / agent_context.py / model_router.py。
3. **92 任务未翻译**：`cron_convert.py` 只转了 81 个且只抽命令；
   agent 平台任务需要**全文 prompt** 翻译（本方案的 `nano_sched_convert.py` 已补，92/92）。
4. **delivery 语义**：.md 的 `delivery.chat_id` 指向 Muse 主聊天；Windows 侧改为
   nanoMuse console inbox（deferred，见 §7 未决）。

---

## 2. Windows 部署架构（文字版架构图）

```
┌─ 新 Windows VPS ─────────────────────────────────────────────┐
│                                                              │
│  C:\ProgramData\nanoMuse\  (NANOMUSE_BASE)                   │
│  ├── venv\                      Python 3.11 venv             │
│  ├── scheduler\                                                 │
│  │   ├── scheduler.py            APScheduler（复用，加 agent 接线）
│  │   ├── jobs.yaml               77 现有 + 92 新增（mode=agent）
│  │   ├── ownership.db            单写者租约（SQLite，跨平台）
│  │   └── agent_context.py        hydrate_and_run（路径抽象后）  │
│  ├── config\nanomuse.toml       BYOK 模型配置                 │
│  ├── cron_agent\                 agent 会话/审计落盘           │
│  └── logs\                       调度器日志                    │
│                                                              │
│  Windows Service「nanoMuse Scheduler」                          │
│    └─ NSSM 包装：venv\Scripts\python.exe scheduler\scheduler.py │
│       （备选：pywin32 原生 service；再备选：Task Scheduler 开机任务）
│                                                              │
│  衔接 windows_compat\：                                        │
│    ├── tunnel_py.py    反向隧道（8735 nanoMuse MCP 等）          │
│    ├── config.py       DATA_DIR 三级优先级（与 NANOMUSE_BASE 对齐）│
│    └── sched_win.py    21 直接命令 → Task Scheduler XML（不变）  │
│                                                              │
│  数据面（与 Linux 同构）：                                      │
│    C:\ProgramData\Perpetua\data\  ← snapshot.py/restore.py 迁移 │
└──────────────────────────────────────────────────────────────┘
        │ HTTPS/隧道                │ 影子diff回传（只读）
        ▼                           ▼
  viralloopapp.com /           Linux 本机（开发/备份，调度停写）
  nano.viralloopapp.com
```

### 架构选型（已定）

| 决策 | 选型 | 理由 |
|---|---|---|
| 调度器 | 复用 nanoMuse APScheduler，不另起炉灶 | 77 任务已跑、执行门/M1 已修、租约机制现成 |
| agent 任务执行 | `mode=agent` 接线 `hydrate_and_run` | 全文 prompt 执行，BYOK 路由已通 |
| 常驻方式 | NSSM → Windows Service | 对标 Linux systemd；崩溃自动重启；开机自启 |
| 21 直接命令 | 保持 sched_win.py 的 Task Scheduler XML | 已验证 113/113 合法，不重复造轮子 |
| 路径 | `NANOMUSE_BASE` 环境变量（默认 C:\ProgramData\nanoMuse） | 对齐 windows_compat/config.py 三级优先级模式 |

---

## 3. 代码改动清单（Windows 侧，不动 Linux 生产）

> 全部在 Windows 部署的代码副本上改；Linux 侧 `/home/hatch/data/nanomuse-migration`
> 只读调研，不动。

1. **路径抽象**（3 文件）：
   - `scheduler.py`：`BASE = os.environ.get("NANOMUSE_BASE", "/home/hatch/data/nanomuse-migration")`
   - `agent_context.py`：`BASE`、`CRON_WORKSPACE`、`CRON_DATA_DIR` 同理环境变量化；
     `hydrate_goal()` 的 `Path.home()/workspace/goals` 改为 `Path(os.environ.get("WORKSPACE_HOME", ...))`
   - `model_router.py`：`LLM_ASSETS` 环境变量化（默认 `%PROGRAMDATA%\nanoMuse\llm_assets`）
2. **接线 agent 执行**（`scheduler.py`）：
   - `run_shadow_job` 内：`if job.get("mode") == "agent" and gate_allow: return hydrate_and_run(...)`
   - `_execution_decision()` 加 `mode == "agent"` 分支：仅 `ownership.writer == 'nanomuse'` 放行
     （与 full 同门；`manual`/`runonce` 永不自动执行）
   - `main()` 加载时跳过 `mode in ("manual", "runonce")`（runonce 由一次性 runner 消费）
3. **任务清单扩展**：`nano_agent_jobs.json`（本方案翻译器产出，92 个）合并进 `jobs.yaml`
   （`mode: agent`，`agent_prompt` 全文，`timeout_s` 按间隔）。
4. **翻译器纳入自动同步**：`nano_sched_convert.py` 加入 `build_windows_migration_package.sh`
   或 install-package-sync 链路（cron .md 变化 → jobs.yaml 重建 → 调度器热加载）。

---

## 4. 安装步骤（新 Windows VPS）

```
1. 前置：Windows Server 2019+、管理员、Python 3.11+、OpenSSH 客户端、NSSM
2. 解包：perpetua-windows-migration-YYYYMMDD.tar.gz → C:\PerpetuaDeploy\
3. 装 nanoMuse 代码（GPL 源码包/迁移包内 code/nanomuse-migration/）
   → C:\ProgramData\nanoMuse\；建 venv，pip install -r requirements
4. 配环境变量：NANOMUSE_BASE=C:\ProgramData\nanoMuse；
   WORKSPACE_HOME=C:\PerpetuaDeploy；DATA_DIR=C:\ProgramData\Perpetua\data
5. 放 BYOK 凭据到 %PROGRAMDATA%\nanoMuse\llm_assets\（agnes.env/gemini-auto.env，
   不进包，人工放，600 等效 ACL）
6. 数据迁移：tools_win\snapshot.py（Linux）→ 拷到新机 → restore.py
7. 注册服务：nssm install nanoMuseScheduler <venv>\Scripts\python.exe
   C:\ProgramData\nanoMuse\scheduler\scheduler.py
   nssm set nanoMuseScheduler Start SERVICE_AUTO_START
8. 导入 21 直接命令：sched_win.py 产出的 XML → schtasks /CREATE /XML（install_windows.bat 已含）
9. 冒烟：verify.py 全量；查 scheduler.log 确认 169 任务加载、GATE-DENY 预期数量
```

---

## 5. 双跑切换方案（B 路线：影子 → 切流 → 回滚）

| 阶段 | 动作 | 验证点 | 回滚 |
|---|---|---|---|
| P0 影子 | Windows 调度器启动，92 任务 `ownership.writer=muse`（GATE-DENY，只加载不执行）+ 10 个低风险任务开 shadow 只读 | scheduler.log 无 failed_parse；影子输出与 Linux diff 一致 | 停 Windows 服务 |
| P1 影子执行 | 选 5 个只读任务 writer→nanomuse（shadow 模式跑，写影子目录不碰生产） | 影子输出落盘正常；生产 DB/队列零写入（审计） | writer 切回 muse |
| P2 逐个切流 | 按"用户停旧→nanoMuse 开新→验证"逐个来（沿用 10-14 两步流程）；先非浏览器任务，浏览器 7 平台等用户手动重登后 | 每个任务：1 个完整周期正常 + handoff/心跳可查 | 单任务 writer 切回 muse（ownership.db 单行更新，秒级） |
| P3 全量 | 92 个 writer 全为 nanomuse；Linux 侧 cron 保持 enabled 但不再是 writer | 24h 无 GATE-DENY 异常；发布/健康指标与基线一致 | 批量 writer 切回（脚本，<5min） |
| P4 退役 | Linux 本机调度停用（disabled），保留为开发/备份 | 影子 diff 连续 7 天一致 | 重新 enabled |

**铁律**（沿用既有）：单写者——任意时刻一个任务只有一个 writer；
回切永不自动（人工批准）；浏览器任务在用户重登前保持 manual/GATE-DENY。

---

## 6. 翻译器覆盖率（2026-10-16 实测）

- 工具：`windows_compat/nano_sched_convert.py`（复用 sched_win 解析，全文 prompt 保留）
- 结果：**92/92 翻译成功**（89 常规 + 3 runonce 带 fire_at），5 跳过全为 disabled（正确）
- 全部 schedule 经 nanoMuse 真实 `parse_cron` 验证通过，0 失败
- 产物：`windows_compat/nano_agent_jobs.json` + `NANO_COVERAGE.txt`
- 超时策略：interval 按间隔-30s（180~900s）；daily/weekly/runonce 900s

---

## 7. 未决事项（需用户/新 VPS 信息）

1. **新 VPS 规格**：IP、Windows Server 版本、管理员账号、Python 是否已装——决定 install
   步骤细节。
2. **BYOK 凭据落盘**：agnes.env / gemini-auto.env 需人工放到新机 llm_assets（不进包）。
3. **浏览器登录态**：7 平台等用户手动重登；相关任务在重登前保持 manual。
4. **delivery 改道**：92 任务的 `delivery.chat_id` 指向 Muse 主聊天；Windows 侧改为
   nanoMuse console inbox——需确认用户接受（或保留转发达 Linux）。
5. **Linux 侧调度器现状**：本次调研时 `scheduler.py` 进程未在运行（systemd unit 未找到），
   需确认是预期停机还是异常——影响 P0 影子基线。
6. **runonce 3 个**（ep1-sniper-48h/7d、title-spec-30day-tripwire）：一次性 runner 待写
   （消费后删除），或到期前人工执行。
7. **30s 级任务**（viralloop-oa-refresh）：APScheduler 支持 interval:30s，但 agent
   冷启动开销大——建议 P2 前实测单次耗时，超 20s 则降频或转直接命令。
