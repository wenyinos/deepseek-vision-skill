---
name: deepseek-vision
description: >
  Use first whenever the user sends images, audio, video, screenshots, or mixed
  documents containing non-text media, or asks you to see, hear, or analyze such
  content. Routes media through Xiaomi MiMo V2.5 (mimo-v2.5) and uses
  mimo-v2.5-asr for transcription, then reports Token Plan token usage or
  pay-as-you-go RMB cost. Pure text requests do not trigger this skill.
---

# DeepSeek Vision

## 能力边界（先读这一节）

- 你是文本处理模型，不能直接“看到”图片、“听到”音频，也不能直接“观看”视频。
- 遇到非文本内容禁止猜测、禁止假装理解、禁止直接报错；先调用本 skill 的 `scripts/mimo.py` 获取 MiMo V2.5 的处理结果，再基于结果回答用户。
- 纯文本请求不要调用 MiMo，由你自己处理。
- 混合内容（例如带图片的 Word/PDF）：文本部分由你自己处理，媒体部分交给 MiMo；不要把整个大文档塞给 MiMo。

## 全局配置与切换

- 配置是全局共享的，一次配置后所有对话、新开任务、重启后都继续使用，不需要重新配置。
- 真实 API Key 和 Token Plan 专属 Base URL 不写入本 skill 目录；它们由 `mimo.py` 保存到系统安全存储或用户目录下的外部配置中。
- 首次配置前，先向用户说明两种方式都可使用：
  - 按量付费：key 格式 `sk-xxxxx`，在控制台 API Keys 创建，Base URL 为 `https://api.xiaomimimo.com/v1`。
  - Token Plan：key 格式 `tp-xxxxx`，在 `https://platform.xiaomimimo.com/token-plan` 订阅，从 Token Plan 页面复制专属 API Key 和专属 Base URL。

```bash
python3 scripts/mimo.py configure --plan payg
python3 scripts/mimo.py configure --plan token --base-url "https://你的专属TokenPlan地址/v1"
python3 scripts/mimo.py status
python3 scripts/mimo.py check
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

脚本输出 JSON，取 `content` 字段作为 MiMo 的处理结果。信息不足时可以继续用更小的问题或更高的 `--max-tokens` 再请求一次，但不要臆测媒体内容。

以上命令请在 skill 目录下运行；非交互式配置可通过 `MIMO_API_KEY` 环境变量提供 key，Token Plan 再通过 `--base-url` 提供专属 Base URL。

## 使用 MiMo 后必须告知用量

只要本次回答使用了 MiMo，最终回复必须追加一句简短说明：

- Token Plan：`已通过 MiMo V2.5 处理 · Token Plan · 本次约 N tokens`
- 按量付费：`已通过 MiMo V2.5 处理 · 按量付费 · 本次约 ¥0.xxxx`

按量付费金额来自脚本返回的 `cost_cny`；Token Plan token 数来自 `tokens`。如果 `cost_cny` 为 null，说明无法精确计价，应注明“金额以官方账单为准”。

## 错误处理

- 遇到错误先自行处理：网络/429/5xx 自动重试；文件超限或格式不支持先压缩、转码或改用公网 URL；`finish_reason=length` 时提高 `--max-tokens` 或缩小问题；认证失败先检查 key 前缀、active plan、Base URL 是否匹配，并提示重新 `configure` 或切换 plan。
- 自行处理仍失败时，必须明确告诉用户：哪一步失败、错误码/API 原始错误信息（脱敏）、文件路径与大小、建议的修复动作。
- 不得静默忽略错误、不得伪装成功、不得猜测媒体内容、不得泄露 key 或完整 Base URL。

## 跨平台说明

- macOS：优先使用 Keychain。
- Windows：优先使用 DPAPI 加密凭据。
- Linux/其他：回退到用户目录下权限受限的 JSON 配置。
- 所有路径由 Python `pathlib`/环境变量计算，不依赖 POSIX 专属写法。
