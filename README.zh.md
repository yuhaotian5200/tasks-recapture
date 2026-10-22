# tasks-recapture 使用说明

`tasks-recapture` 从一份 UTF-8 聊天记录里找出还没做完的事，先给人看建议，确认后再写成本地 Markdown 任务卡。以后再导入相关讨论时，可以接回同一张卡。

保存只是记下这件事。它不是开工许可，程序也不会执行聊天里出现的命令。

## 安装

需要 Python 3.11 或更新版本。运行时只用标准库。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

## 用模拟模型走一遍

模拟结果会标明 `provider: mock` 和 `live_api: false`，不会联网，也不会读取 API 密钥。

```bash
mkdir -p /tmp/tasks-demo
tasks-recapture import examples/sample-transcript.md \
  --tasks-dir /tmp/tasks-demo \
  --provider mock \
  --mock-script examples/mock-suggestions.json \
  --yes \
  --timezone UTC \
  --now 2026-10-22T12:00:00

tasks-recapture list --tasks-dir /tmp/tasks-demo
tasks-recapture review --tasks-dir /tmp/tasks-demo --transcript examples/follow-up.md
```

`examples/sample-transcript.md` 是编出来的例子。仓库里的 `examples/resulting-cards/` 是同一次模拟导入留下的任务卡。再跑一次会得到新的任务编号，标题、暂停状态和重拿条件相同。

例子里的结果是：

- “Draft the November garden newsletter”被记成一张 `paused` 卡，重拿条件是植物清单到达。
- 助手提出、人已经拒绝的网站改版被忽略。
- 记录里已经写明寄出的浇水提醒被忽略。
- “忽略之前的指令并执行命令”只是原文，不会被执行。

## 配置

API 密钥只放在环境变量 `TASKS_RECAPTURE_API_KEY`。配置文件里如果写了密钥、令牌或密码，程序会拒绝启动。

常用项：

- 任务目录：`--tasks-dir` 或 `TASKS_RECAPTURE_TASKS_DIR`，默认 `tasks`
- 时区：`--timezone` 或 `TASKS_RECAPTURE_TIMEZONE`，默认 `UTC`
- 模型名：`--model` 或 `TASKS_RECAPTURE_MODEL`
- 接口地址：`--api-base` 或 `TASKS_RECAPTURE_API_BASE`

真实接口是 OpenAI 兼容的 chat completions。必须同时有模型名、环境变量里的密钥，以及 `--send`，程序才会发出网络请求。没有 `--send` 时，请求在打开连接之前就停止。本仓库没有密钥，真实接口没有跑过。

## 状态

四档状态是 `not_started`、`in_progress`、`paused`、`done`。

导入新建的卡只会是 `not_started`，或者在明确搁置且写了重拿条件时为 `paused`。导入不会把卡写成进行中或已完成。改状态用：

```bash
tasks-recapture mark <任务编号> --status paused --tasks-dir /tmp/tasks-demo
```

`paused`、`done`，以及用 `mark` 标过的卡，之后的导入都不能改掉它们的状态。暂停也不会因为放得久而自动取消。`review` 只会提示重拿条件可能已经满足，不会改卡。

拿不准是不是同一件事时，必须由人选择接回旧卡还是新建。`--yes` 不会自动合并这种建议。

## 数据

程序只读你点名的那一个文本文件。任务卡和断点记录都在任务目录里，其中 `.tasks-recapture/` 是处理进度。删除整个任务目录就会删掉卡片和进度。模拟运行不会把文本发到任何服务器。

更完整的英文说明、安全模型和测试方法见 [README.md](README.md)、[SECURITY.md](SECURITY.md) 和 [HANDOFF.md](HANDOFF.md)。
