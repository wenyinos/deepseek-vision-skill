# deepseek-vision

让 Codex 等文本模型能“看图、听音、看视频”：把图片、音频、视频交给小米 MiMo V2.5 处理，并统计 Token Plan 用量或按量付费费用。

## 安装

```bash
git clone https://github.com/reF0o0/deepseek-vision.git
cp -r deepseek-vision/deepseek-vision ~/.codex/skills/deepseek-vision
```

首次使用前配置：

```bash
cd ~/.codex/skills/deepseek-vision
python3 scripts/mimo.py configure --plan payg
python3 scripts/mimo.py configure --plan token --base-url "https://你的专属TokenPlan地址/v1"
```

## 使用

```bash
# 理解图片/音频/视频
python3 scripts/mimo.py analyze --files 文件路径 --prompt "描述内容"
python3 scripts/mimo.py analyze --urls 公网URL --prompt "这段音频说了什么"

# 音频转文字
python3 scripts/mimo.py asr --file 音频.mp3 --language auto

# 长时间识别用后台任务
python3 scripts/mimo.py analyze --files 文件路径 --prompt "描述内容" --async
python3 scripts/mimo.py jobs
```

## 注意

- 媒体会以 Base64 上传到小米 MiMo API，敏感内容不要使用。
- 使用会产生费用，key 请妥善保管，不要入库或分享。
- 单文件超过约 50MB 会失败；ASR 只支持 wav/mp3。
