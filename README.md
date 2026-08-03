# deepseek-vision

deepseek-vision 是一个能让 deepseek 在 Codex 里查看图片的 skill。平时 deepseek 只能看懂文字，你发的图片、音频、视频它都看不见、听不到。装上这个 skill 后，deepseek 会先把文件转交给小米的 MiMo V2.5 大模型，请它帮忙“看”和“听”，再把看懂的内容用中文告诉你。你只需要像平时一样把文件发给它、问问题，不需要任何特殊操作；每次使用后它还会告诉你这次消耗了多少 Token 或花了多少钱。

## 它能做什么

- 看图：识别图片里的内容，回答和图片相关的问题。
- 听音：听懂音频内容，也能把音频转成文字。
- 看视频：逐帧理解视频内容，总结视频在讲什么。
- 成本透明：每次使用后都会显示 Token Plan 用量或按量付费金额。
- 配置安全：API Key 保存在系统安全存储中，不会写进仓库或聊天记录。
- 开箱即用：支持本地文件和公网链接，出错会自动重试并给出明确提示。

## 安装

把 [deepseek-vision](https://github.com/reF0o0/deepseek-vision) 这个链接发给 Codex，说“下载并安装这个 skill”。Codex 会帮你完成下载、安装和配置。

也可以到 [Releases 页面](https://github.com/reF0o0/deepseek-vision/releases) 直接下载 skill 压缩包。

## 配置

装好后，在 Codex 对话里直接输入“配置 deepseek-vision”，按提示二选一：

- 按量付费：使用小米开放平台的 API Key。
- Token Plan：订阅 Token Plan 后，使用专属 API Key 和专属 Base URL。

不需要自己敲命令，Codex 会在对话里帮你完成配置。

## 环境要求

- 已安装 [Codex](https://openai.com/zh-Hans-CN/codex/)。
- 已安装 Python 3（脚本只用 Python 标准库，不需要安装其他依赖；还没装的话可到 [Python 官网](https://www.python.org/downloads/) 下载）。
- 已注册 [小米 MiMo 开放平台](https://platform.xiaomimimo.com/console/profile)，并配置自己的 API Key 或 Token Plan。
- 网络能正常访问小米 MiMo API。

## 怎么用

不需要记命令，直接在 Codex 对话里说需求：

- 想识别图片：把图片发给 Codex，问“这张图片里有什么”。
- 想听音频：把音频发给 Codex，问“这段音频说了什么”。
- 想转文字：把音频发给 Codex，说“把这段音频转成文字”。
- 想看视频：把视频发给 Codex，说“总结一下这个视频的内容”。
- 识别比较慢时，Codex 会改用后台任务处理，完成后把结果告诉你。

## 使用前须知

- 隐私提醒：图片、音频、视频会以 Base64 形式上传到小米 MiMo API 处理，涉及机密或敏感内容时请勿使用。
- 费用说明：按量付费按 token 和音频时长计费，Token Plan 会消耗订阅配额；文件越大、帧率越高、音频越长，费用越高。
- 文件限制：单个文件超过约 50MB 无法处理；音频转文字目前只支持 wav 和 mp3。
- 网络要求：需要能正常访问小米 MiMo API 的网络环境。
- 安全提醒：请妥善保管 API Key，不要分享给别人，也不要写进代码或仓库。
