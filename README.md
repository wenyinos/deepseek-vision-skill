# deepseek-vision

deepseek-vision 是一个给 Codex 使用的技能。它解决的问题是：Codex 这类文本模型看不到图片、听不到音频，也看不了视频。安装这个技能后，Codex 会把图片、音频、视频交给小米的 MiMo V2.5 大模型处理，再把处理结果带回来回答你，并告诉你这次用了多少 Token 或花了多少钱。

## 它能做什么

- 看图：识别图片里的内容，回答和图片相关的问题。
- 听音：听懂音频内容，也能把音频转成文字。
- 看视频：逐帧理解视频内容，总结视频在讲什么。
- 成本透明：每次使用后都会显示 Token Plan 用量或按量付费金额。
- 配置安全：API Key 保存在系统安全存储中，不会写进仓库或聊天记录。
- 开箱即用：支持本地文件和公网链接，出错会自动重试并给出明确提示。

## 安装

两步即可完成：

1. 打开终端，把本仓库下载到电脑，并复制到 Codex 的技能目录：

```bash
git clone https://github.com/reF0o0/deepseek-vision.git
cp -r deepseek-vision/deepseek-vision ~/.codex/skills/deepseek-vision
```

2. 配置 MiMo 账号，二选一：
   - 按量付费：使用小米开放平台的 API Key。
   - Token Plan：订阅 Token Plan 后，使用专属 API Key 和专属 Base URL。

```bash
cd ~/.codex/skills/deepseek-vision
python3 scripts/mimo.py configure --plan payg
python3 scripts/mimo.py configure --plan token --base-url "https://你的专属TokenPlan地址/v1"
```

配置完成后，新建一个 Codex 对话，把文件发给它并说明问题即可。

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
