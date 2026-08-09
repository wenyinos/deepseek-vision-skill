# deepseek-vision skill

deepseek-vision 是一个多平台 skill，让本身没有视觉能力的模型也能处理图片、音频和视频。支持 Codex、Claude Code、OpenCode。遇到非文本内容时，交给小米 MiMo 模型处理，再基于 MiMo 返回的信息回答用户问题。

## 能力

- 图片理解：识别图片内容，回答与图片相关的问题。
- 音频理解：听懂音频内容、支持转文字/听写。
- 视频理解：按帧理解视频内容并总结。
- 分工明确：文本部分由 agent 自己处理，媒体部分交给 MiMo，不把整个大文档塞给 MiMo。
- 强制路由：图片和截图不会走本地 OCR 或原生视觉，统一交给 MiMo 处理。
- 用量透明：使用Token Plan 与 OpenCode Go 会显示使用 token 数，使用 API 会显示使用人民币金额。
- 全局配置：全局配置一次，任意对话、新开任务、重启后都能继续使用。
- 多对话可用：MiMo 返回内容只在当前对话使用，不跨对话共享，可多对话同时使用。
- 后台任务：识别较久时会进入后台，对话被中断后结果仍可取回。

## 安装

1  把[仓库链接](https://github.com/reF0o0/deepseek-vision-skill)发给 Codex，说“下载并安装这个 skill”，Codex 会自动完成下载、安装。

2  从 [Releases 页面](https://github.com/reF0o0/deepseek-vision-skill/releases) 下载 skill 压缩包，解压后把其中的 `deepseek-vision` 目录放到对应平台的 skill 目录：

   - Codex：`~/.codex/skills/deepseek-vision/`
   - Claude Code：`~/.claude/skills/deepseek-vision/`（或项目内 `.claude/skills/deepseek-vision/`）
   - OpenCode：`~/.config/opencode/skills/deepseek-vision/`（或项目内 `.opencode/skills/deepseek-vision/`）

## 配置

在任意 Codex、Claude Code 或 OpenCode 对话里说“配置 deepseek-vision”后，按引导完成配置。

支持:

- API： 格式 `sk-xxxxx`。
- Token Plan： 格式 `tp-xxxxx`。
- OpenCode Go： 格式 `sk-xxxxx`，通过 OpenCode Zen Go 端点接入（仅支持图片/视频理解，不支持音频 analyze 与 ASR；音频请求会自动回退到已配置的 payg/token 官方渠道，未配置时会提示先配置官方渠道）。

## 使用

在对话里直接发送图片、音频、视频并提问即可。

## 超时与失败

- MiMo 处理媒体通常需要几十秒到几分钟，默认请求超时 180 秒；请不要在 60 秒左右就判定失败，并耐心等待结果。如请求失败，agent 会明确告知或重试。

## 安全与隐私

- 默认请求走 Python 标准库，API Key 和 Base URL 不进入进程参数；若默认通道被服务商以 HTTP 403 拒绝（如 Cloudflare 指纹拦截），脚本会自动改用 curl 重试，无需手动干预；也可显式设置 `MIMO_USE_CURL=1` 强制走 curl，此时 key 通过临时配置文件传递，仍不会出现在命令行。
- 真实 API Key 和 Token Plan 专属 Base URL 不写入本 skill 目录，也不写入仓库。
- macOS 使用 Keychain 分块存储，Windows 使用 DPAPI，Linux/其他系统回退到 `600` 权限的用户目录配置。
- 运行时会脱敏模型 Base64 和带参数的 URL；agent 不把媒体内容写入任何日志。
- 异步任务结果只在当前用户目录以 `600` 权限暂存，`poll` 取走后立即删除，超过 24 小时自动清理。
- 重要信息会脱敏，不泄露 key 或完整 Base URL。

## 环境要求

- 已安装 [Codex](https://openai.com/zh-Hans-CN/codex/)、[Claude Code](https://code.claude.com/docs/en/setup) 或 [OpenCode](https://opencode.ai/docs/)（任一即可）。
- 已安装 [Python](https://www.python.org/downloads/)
- 已注册 [小米 MiMo 开放平台](https://platform.xiaomimimo.com/console/profile) 并配置 API Key 或 Token Plan，或已获取 OpenCode Go 渠道的 API Key。

## 注意事项

- Python脚本使用终端运行，skill默认直连MiMo，不使用代理。
- 媒体会以 Base64 形式上传到远程 API 处理，涉及机密或敏感内容时请勿使用。
- 单个本地文件超过约 50MB 后会无法处理；音频转文字目前只支持 `wav` 和 `mp3`。
- 请妥善保管 API Key，不要写进代码、仓库或聊天记录。
- 本skill不具有图片，视频等非文本内容生成功能。
