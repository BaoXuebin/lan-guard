# 🛡️ LAN Guard

用闲置手机 + 家里电脑，几分钟搭出一个**纯局域网**的 **AI 看护摄像头**。

[English](#english) | 中文

> 🔭 **一个引擎，多种场景**：推流/采样/视觉分析/状态机告警/网页与"场景"完全解耦。
> 内置场景包：**婴儿睡眠监护**、**居家养老看护**（跌倒告警、久卧翻身提醒）。
> 在 `scenes/` 目录用一个 YAML（提示词 + 状态 + 规则）就能定义自己的场景——宠物、门口、看店……
>
> （本项目原名 baby-monitor，现已场景化并更名）

## 它能做什么（婴儿睡眠监护场景）

- 📹 **实时画面**：旧 iPhone 锁屏推流，家里任何手机浏览器打开网页即可看（WebRTC 低延迟，HLS 兜底）
- 🛌 **睡姿监测**：识别仰卧 / 左侧卧 / 右侧卧 / 趴卧；单侧睡过久自动提醒换边
- 😴 **觉醒监测**：识别宝宝是否醒了 / 睡着，状态实时更新
- 🚨 **突发告警**：趴睡、口鼻遮挡、离开画面 → 网页弹窗 + 响铃；本地哭声检测（不经云端）
- 🔒 **隐私**：视频流全程不出局域网；仅可选把采样帧发给视觉大模型分析
- 💰 **成本**：视觉分析按 15 秒/帧估算，一夜约几毛到一两元（也可完全关闭，退化为纯视频监控）

> ⚠️ 本项目是**辅助工具，不能替代**专业医疗监护设备和成人看护，详见 [DISCLAIMER.md](DISCLAIMER.md)。

## 架构

```
旧 iPhone（Larix Broadcaster，锁屏推流）
        │ RTMP（局域网）
        ▼
常开主机（Windows / Linux / macOS / NAS）
 ├─ MediaMTX：接收推流 → WebRTC/HLS 分发给浏览器
 └─ Python 服务（FastAPI）
     ├─ 画面采样 → 视觉大模型（智谱 GLM-4.5V / 任意 OpenAI 兼容视觉模型）
     ├─ 音频分析 → 本地哭声检测（响度+频谱启发式，不上云）
     └─ 状态机 → 睡姿计时 / 觉醒判定 / 异常告警 / 事件日志
        │ HTTP（局域网）
        ▼
其他手机浏览器：实时画面 + 状态面板 + 响铃告警
```

## 快速开始（Windows）

### 1. 准备

- Python 3.10+、ffmpeg（放到 `tools/bin` 或 PATH 中，可用 `FFMPEG_PATH` 指定）
- 下载 [MediaMTX](https://github.com/bluenviron/mediamtx/releases) 解压到 `tools/bin/mediamtx/`

### 2. 配置

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy config.example.yaml config.yaml   # 修改 access_token 等设置
copy .env.example .env                 # 填入智谱 API Key（不用视觉分析可跳过）
```

### 3. 启动

```bash
# 终端 1：MediaMTX
tools\bin\mediamtx\mediamtx.exe deploy\mediamtx.yml

# 终端 2：监控服务
.venv\Scripts\python -m backend.run
```

### 4. iPhone 推流（两种方式任选）

- **浏览器（零安装，推荐）**：见 [docs/iphone-setup.md](docs/iphone-setup.md)。
  iPhone Safari 打开 `https://<电脑IP>:8443/push` 一键推流（首次需安装本地证书，3 分钟）
- **Larix App**：免费 App 推流，优点是锁屏也能推流（浏览器方式需屏幕常亮）

### 5. 查看

家里其他手机浏览器打开 `http://<电脑IP>:8080`，输入访问口令。

### 没有旧手机？先在本机试试

```bash
# 用 ffmpeg 造一个假摄像头推流，验证整条链路
ffmpeg -re -f lavfi -i "testsrc2=size=640x480:rate=15" -f lavfi -i "sine=frequency=600:sample_rate=16000" -c:v libx264 -preset veryfast -g 30 -c:a aac -b:a 64k -f flv rtmp://127.0.0.1:1935/baby
```

## 配置要点

| 配置 | 说明 |
|---|---|
| `server.access_token` | 网页访问口令，**务必修改** |
| `vision.provider` | `zhipu` / `openai_compat` / `mock`（调试）/ `disabled`（纯局域网模式） |
| `scene` | 场景包路径，也可在网页"设置"页切换（提示词/状态/告警规则随场景生效） |
| `stream.analyze_interval` | 有动静时送视觉模型分析的间隔（秒），默认 15 |
| `audio.cry_threshold_rms` | 哭声响度阈值，需按房间环境噪声微调 |

所有密钥只放 `.env`（已被 `.gitignore` 排除）。

## 项目结构

```
backend/          FastAPI 服务：采样、分析、状态机、API
  providers/      视觉模型抽象层（智谱 / OpenAI 兼容 / mock）
web/              前端单页（WebRTC 播放、状态面板、告警响铃）
deploy/           MediaMTX 配置、启动脚本
docs/             iPhone 配置、部署指南
```

## English

**LAN Guard** turns a spare phone + a home computer into a **LAN-only** AI caretaker camera. The engine (streaming → sampling → VLM analysis → alert state machine → web dashboard) is fully decoupled from the use case via *scene profiles*: a single YAML defines the vision prompt, states and alert rules. Built-in scenes: **baby sleep monitoring** (posture/side-sleep alerts, cry detection) and **elderly care** (fall detection, bedsore-prevention turn reminders). Vision analysis works with any OpenAI-compatible VLM (Zhipu GLM-4.5V by default); a fully cloud-free mode is also supported. See quick start above; disclaimer in [DISCLAIMER.md](DISCLAIMER.md).

## License

MIT，见 [LICENSE](LICENSE)。
