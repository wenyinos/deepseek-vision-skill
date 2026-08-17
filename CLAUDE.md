# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

deepseek-vision 是一个多平台 skill（支持 Codex / Claude Code / OpenCode）：让本身没有视觉能力的模型也能处理图片/音频/视频。非文本内容由 `deepseek-vision/scripts/mimo.py` 交给小米 MiMo V2.5（`mimo-v2.5`）理解，音频转文字走 `mimo-v2.5-asr`。SKILL.md 规定 agent 必须忽略自身本地视觉能力，只信 MiMo 返回的 `content`。

## 目录结构

- `deepseek-vision/SKILL.md` — 技能定义与运行时行为指令（agent 的调用/安全/错误处理约束）
- `deepseek-vision/scripts/mimo.py` — 唯一实现，单文件 Python CLI，仅依赖标准库；m4a 转码需要 ffmpeg
- `deepseek-vision/agents/openai.yaml` — Codex agent 元数据
- `deepseek-vision/config.example.json` — 配置结构模板（active_plan + payg/token/opencode_go 凭据 + pricing 价格表）
- `README.md` — 面向用户的安装/配置/使用文档

## 常用命令

无构建、测试、lint 体系；所有命令在 `deepseek-vision/` 目录下运行：

```bash
python3 scripts/mimo.py status           # 查看配置状态（输出脱敏）
python3 scripts/mimo.py check            # 校验当前凭据能否连通 MiMo API
python3 scripts/mimo.py diagnose         # 诊断配置 / DNS / 网络连通性
python3 scripts/mimo.py analyze --files <媒体路径> --prompt "<问题>"    # 图片/音频/视频理解
python3 scripts/mimo.py asr --file <音频>                               # 音频转文字（仅 wav/mp3）
python3 scripts/mimo.py analyze --files <媒体> --prompt "<问题>" --async # 后台排队，返回 job_id
python3 scripts/mimo.py poll --job <job_id> --wait 120                 # 轮询取回后台结果
python3 scripts/mimo.py jobs            # 列出后台任务（24h 后自动清理）
python3 scripts/mimo.py client status                    # 检测三端安装/配置/运行状态
python3 scripts/mimo.py client enable --client codex     # 放行 Codex 图片/音频粘贴（备份+验证+回滚）
python3 scripts/mimo.py client enable --client claude    # 安装 Claude Code 粘贴 hook
python3 scripts/mimo.py client restore --client codex    # 从备份恢复 Codex 模型目录
python3 scripts/mimo.py opencode-paste-extract           # 从 OpenCode 会话库提取最近粘贴的图片
python3 scripts/mimo.py claude-paste-extract             # 从 Claude 会话记录提取最近粘贴的图片
```

所有命令输出 JSON，媒体处理结果在 `content` 字段。

## 架构要点

### 命令分发
argparse 子命令 → `main()` 内 handlers 字典 → 各 `cmd_*` 函数。`MiMoError`（带 `code`）在 `main()` 统一捕获，输出 `ok: false` + `code` 并以非零码退出。

### 凭据存储（跨平台分层 + 双写备份）
- macOS 用 Keychain（分块存储，每块 100 字符）、Windows 用 DPAPI、其他平台 `~/.config/deepseek-vision/credentials.json`（600 权限）
- `save_config` 同时写系统安全存储和用户目录文件；`load_config` 读系统存储失败时回退文件，两份以 `saved_at` 较新者为准。注意用户目录文件是明文备份，不能等同于系统级加密存储
- 环境变量 `MIMO_API_KEY` / `MIMO_BASE_URL` 支持非交互配置；`MIMO_CREDENTIAL_BACKEND=file` 强制文件后端
- 安全红线：真实 key 与专属 Base URL 永不进入命令行参数或本仓库，状态/错误/请求体输出全部脱敏（key 只露首尾 4 位，Base64 媒体显示 `data:<media>;base64,***`）

### 请求与认证
- 默认 urllib 标准库直连，显式 `ProxyHandler({})` 绕过系统/终端代理；`MIMO_USE_CURL=1` 时改走 curl 且强制 `--noproxy '*'`
- 认证头先试 `api-key`，401/403 时自动换 `Bearer` 再试
- 默认超时 180 秒（`DEFAULT_TIMEOUT`），可用 `MIMO_TIMEOUT` 或 `--timeout` 覆盖；`finish_reason=length` 时自动将 `max_completion_tokens` 翻倍重试（上限 4096）

### 异步后台任务
`--async` 把 job 写入 `~/.config/deepseek-vision/jobs/*.json`（600 权限），`_spawn_worker` 派发独立 worker 进程；worker 抢配置锁后循环领取 pending 任务，job 超时后重置为 pending 可被重新领取。结果 24 小时自动清理，`poll` 取走后立即删除。

### 费用
payg 模式按 `config.pricing` 中的人民币/百万 token 价格表计算 `cost_cny`；Token Plan 与 OpenCode Go 只返回 `tokens`。价格表随 `config.example.json` 提交，实际以用户本地 config 为准。

### 客户端接入（Codex / OpenCode / Claude Code）

- `client status` 只读检测三端：Codex 模型目录可解析性（用 `codex debug models` 验证）、OpenCode 的 server/auth/会话库、Claude 安装与 hook 状态，输出 JSON，不修改任何文件。
- `client enable --client codex`：只改 slug 含 `deepseek` 的模型的 `input_modalities` 为 `text/image/audio`（集合比较，任意顺序都视为已启用）；改前备份 `models.json.bak-<时间戳>`，改后用 `codex debug models -c 'model_catalog_json="<路径>"'` 验证，失败自动回滚并报错。
- 硬约束：`input_modalities` 只接受 `text` / `image` / `audio`，**绝不写 `video`**——写入 `video` 会导致整个目录解析失败（`unknown variant "video"`），Codex 启动时回退内置 GPT 模型目录。
- OpenCode：不做任何配置补丁（DeepSeek API 拒收图片，400 `unknown variant "image_url"`）；`opencode-paste-extract` 从 `~/.local/share/opencode/opencode.db` 的 `part` 表读取 `type=file` + `mime=image/*` 的 base64 data URL，落盘 `<cwd>/work/media`，默认只取最新一张，`--all` 取全部。
- Claude Code：`client enable --client claude` 写入 `~/.claude/hooks/deepseek-vision-save-paste.py` 并注册 `UserPromptSubmit` hook（解析会话 jsonl 中的 base64 image 块落盘）；`claude-paste-extract` 直接从 `~/.claude/projects/*/*.jsonl` 提取。两条路径都禁止用 Claude 原生 `Read` 读图。
- 兜底：所有客户端都可把媒体放 `work/media` 发路径，走 `analyze` / `asr`；视频一律走文件路径 + `--fps`，不声明为输入类型。

## 注意事项

- SKILL.md 是给 agent 的行为指令，与 mimo.py 逻辑强绑定（脱敏、超时、直连代理、异步任务），改动任一方需保持两处一致
- 文件 Base64 后超过约 50MB 会被拒绝，需压缩/转码或改用公网 URL；`_data_uri` 只支持 png/jpg/gif/webp/bmp、mp3/wav/flac/m4a/ogg、mp4/mov/avi/wmv
- 本仓库 `.gitignore` 排除了 `config.json`/`credentials.json`/`*.env`/`*.local`，真实凭据不得提交
- 客户端接入命令的改动范围：Codex 只动 `~/.codex/models.json`（且仅 deepseek 模型），Claude Code 只动 `~/.claude/settings.json` 与 skill 自带 hook，OpenCode 只读会话库不写配置；重跑 DeepSeek 官方 setup 脚本会把 models.json 重置回 `["text"]`，需重新 enable
