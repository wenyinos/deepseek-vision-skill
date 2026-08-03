---
name: deepseek-vision
description: >
  Use when the user asks to process or understand text, images, audio, video,
  screenshots, or mixed documents. Route media through Xiaomi MiMo V2.5
  (mimo-v2.5) and use mimo-v2.5-asr for transcription, then report Token Plan
  token usage or pay-as-you-go RMB cost. This is not a global or highest-priority
  skill; do not invoke it for unrelated conversations.
metadata:
  tags:
    - vision
    - media
    - mimo
---

# DeepSeek Vision

## 能力边界

- 你是文本处理模型，不能直接“看到”图片、“听到”音频，也不能直接“观看”视频。
- 本 skill 不是全局技能：普通对话、无关任务、日常编程等场景不要调用；只有用户要求处理文本、图片、音频、视频或混合内容时才使用。
- 遇到非文本内容禁止猜测、禁止假装理解、禁止直接报错；先调用本 skill 的 `scripts/mimo.py` 获取 MiMo V2.5 的处理结果，再基于结果回答用户。
- 纯文本请求不要调用 MiMo，由你自己处理。
- 混合内容（例如带图片的 Word/PDF）：文本部分由你自己处理，媒体部分交给 MiMo；不要把整个大文档塞给 MiMo。
- 即使你觉得自己能直接“看到”图片，也必须忽略本地视觉理解；只有 MiMo 返回的 `content` 可以作为媒体内容依据。

## 禁止使用的本地视觉工具

- 禁止使用 `view_image`、本地 OCR、`screencapture`、截图分析、浏览器截图、Chrome DevTools 截图、系统视觉、macOS Vision、图像元数据读取等任何本地图像识别能力来判断媒体内容。
- 禁止用 `imagegen`、`screenshot`、`computer-use`、`chrome-devtools`、`playwright` 等工具“看图”或代替 MiMo。
- 用户发图片/音频/视频时，只允许通过本 skill 的 `mimo.py` 把媒体交给 MiMo V2.5；本地工具最多只用于确认文件路径、格式和大小，不能用于理解内容。

## 全局配置与切换

- 配置是全局共享的，一次配置后所有对话、新开任务、重启后都继续使用，不需要重新配置。
- 真实 API Key 和 Token Plan 专属 Base URL 不写入本 skill 目录；它们由 `mimo.py` 保存到系统安全存储或用户目录下的外部配置中。
- 配置会同时写入系统安全存储和用户目录下权限受限的外部备份；系统安全存储偶发不可读时，脚本会自动使用备份，避免误报“未配置”。
- 如果 `status` 或 `check` 返回“尚未配置”，先运行 `python3 scripts/mimo.py status` 确认；确认确实未配置后再运行 `configure`，不要把已有配置覆盖掉。
- 首次配置前，先向用户说明两种方式都可使用：
  - 按量付费：key 格式 `sk-xxxxx`，在控制台 API Keys 创建，Base URL 为 `https://api.xiaomimimo.com/v1`。
  - Token Plan：key 格式 `tp-xxxxx`，在 `https://platform.xiaomimimo.com/token-plan` 订阅，从 Token Plan 页面复制专属 API Key 和专属 Base URL。

```bash
python3 scripts/mimo.py configure --plan payg
python3 scripts/mimo.py configure --plan token --base-url "https://你的专属TokenPlan地址/v1"
python3 scripts/mimo.py status
python3 scripts/mimo.py check
python3 scripts/mimo.py diagnose
```

用户说“切换到 Token Plan / 改用 Token Plan”时运行 `python3 scripts/mimo.py use --plan token`；说“切换到 API Key / 改用按量付费”时运行 `python3 scripts/mimo.py use --plan payg`；说“查看当前配置”时运行 `status`。切换后立即全局生效。

## 处理非文本内容

```bash
# 图片/音频/视频理解
python3 scripts/mimo.py analyze --files /path/to/file.png --prompt "描述这张图片"
python3 scripts/mimo.py analyze --files /path/to/video.mp4 --prompt "总结视频内容" --fps 1
python3 scripts/mimo.py analyze --urls https://example.com/a.mp3 --prompt "这段音频说了什么"

# 音频转文字/听写
python3 scripts/mimo.py asr --file /path/to/audio.mp3 --language auto

# 不发送请求，只检查请求体（key 与 Base URL 会脱敏）
python3 scripts/mimo.py analyze --files /path/to/file.png --prompt "测试" --dry-run
```

多对话或识别可能较久时，优先使用后台排队模式，避免长时间占用当前对话的命令会话：

```bash
python3 scripts/mimo.py analyze --files /path/to/file.png --prompt "描述这张图片" --async
# 返回 job_id 后轮询结果
python3 scripts/mimo.py poll --job <job_id> --wait 30
```

`poll` 返回 `status: pending` 时稍等再轮询；返回 `done` 后输出与同步模式相同的 JSON，`error` 则输出明确错误。后台任务由独立进程执行，不会阻塞当前对话。

脚本输出 JSON，取 `content` 字段作为 MiMo 的处理结果。信息不足时可以继续用更小的问题或更高的 `--max-tokens` 再请求一次，但不要臆测媒体内容。

以上命令请在 skill 目录下运行；如果当前目录不是 skill，可先执行 `cd ~/.codex/skills/deepseek-vision`，或直接使用绝对路径 `python3 ~/.codex/skills/deepseek-vision/scripts/mimo.py`。非交互式配置可通过 `MIMO_API_KEY` 环境变量提供 key，Token Plan 再通过 `--base-url` 提供专属 Base URL。

## 禁止承诺式回复

- 不要先输出“我正把图片交给视觉模型识别，稍后告诉你”这类话然后结束；必须实际运行 `mimo.py` 并拿到 JSON 结果后才回答。
- 最终回答必须基于脚本返回的 `content`，并在同一条回复里给出结果和 MiMo 用量说明；不要在拿到结果前向用户承诺任何内容。
- 如果不知道附件在本机的实际路径，先查找用户消息中的文件路径；找不到就直接向用户索要路径，不要假装已经发送给 MiMo。
- 如果脚本报错，把脱敏后的错误信息和修复建议直接告诉用户，不要只说“正在处理”或“稍后再试”。

## 使用 MiMo 后必须告知用量

只要本次回答使用了 MiMo，最终回复必须追加一句简短说明：

- Token Plan：`已通过 MiMo V2.5 处理 · Token Plan · 本次约 N tokens`
- 按量付费：`已通过 MiMo V2.5 处理 · 按量付费 · 本次约 ¥0.xxxx`

按量付费金额来自脚本返回的 `cost_cny`；Token Plan token 数来自 `tokens`。如果 `cost_cny` 为 null，说明无法精确计价，应注明“金额以官方账单为准”。

## 错误处理

- 遇到错误先自行处理：网络/429/5xx 自动重试；文件超限或格式不支持先压缩、转码或改用公网 URL；`finish_reason=length` 时提高 `--max-tokens` 或缩小问题；认证失败先检查 key 前缀、active plan、Base URL 是否匹配，并提示重新 `configure` 或切换 plan。
- 如果脚本报 `Could not resolve host` / DNS 错误，说明当前任务没有可用的网络访问；先重试一次，仍失败就直接告诉用户检查 Codex 的网络或“完全访问”权限，不要反复猜测或伪装成功。
- 遇到“无法连接网络”时先运行 `python3 scripts/mimo.py diagnose`；若返回 `dns_ok: false` 或 `network_ok: false`，说明当前对话本身没有网络权限，应让用户在该对话开启网络/完全访问后重试，而不是继续重复请求。
- 多个对话可以并行使用本 skill；如果某个对话正在执行长时间识别，另一个对话稍等重试即可，不要在同一对话里并发启动多个 `analyze` 命令。
- 自行处理仍失败时，必须明确告诉用户：哪一步失败、错误码/API 原始错误信息（脱敏）、文件路径与大小、建议的修复动作。
- 不得静默忽略错误、不得伪装成功、不得猜测媒体内容、不得泄露 key 或完整 Base URL。

## 跨平台说明

- macOS：优先使用 Keychain。
- Windows：优先使用 DPAPI 加密凭据。
- Linux/其他：回退到用户目录下权限受限的 JSON 配置。
- 所有路径由 Python `pathlib`/环境变量计算，不依赖 POSIX 专属写法。
