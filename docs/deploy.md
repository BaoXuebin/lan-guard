# 部署指南

## 端口一览

| 端口 | 用途 |
|---|---|
| 1935 | RTMP，iPhone 推流入口 |
| 8554 | RTSP，服务端取流分析 |
| 8888 | HLS 播放（兜底） |
| 8889 | WebRTC（WHIP 推流 / WHEP 播放），由后端同源代理调用，手机无需直接访问 |
| 8080 | 监控网页 + API |

局域网使用请确保防火墙放行以上端口（Windows 可用下方脚本）。

## Windows

### 手动启动

```bat
:: 终端 1
tools\bin\mediamtx\mediamtx.exe deploy\mediamtx.yml

:: 终端 2
.venv\Scripts\python -m backend.run
```

### 一键脚本

见 `deploy/start-windows.bat`（同时启动两者并缩到托盘最小化窗口）。

### 开机自启（可选）

用任务计划程序创建两个任务（登录时触发）分别运行上述两条命令；或使用 [NSSM](https://nssm.cc) 注册为 Windows 服务：

```bat
nssm install languard-mediamtx "C:\...\tools\bin\mediamtx\mediamtx.exe" "C:\...\deploy\mediamtx.yml"
nssm install languard-app "C:\...\.venv\Scripts\python.exe" "-m backend.run"
nssm set languard-app AppDirectory "C:\..."
```

## Linux / macOS / NAS

MediaMTX 与后端均为跨平台，步骤一致：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.yaml config.yaml   # 修改配置
cp .env.example .env

# MediaMTX（下载 linux/macOS 版）
./mediamtx deploy/mediamtx.yml &
.venv/bin/python -m backend.run
```

### systemd 示例（Linux/NAS 常驻）

```ini
# /etc/systemd/system/babymonitor.service
[Unit]
Description=lan-guard backend
After=network.target

[Service]
WorkingDirectory=/opt/lan-guard
ExecStart=/opt/lan-guard/.venv/bin/python -m backend.run
Restart=always
User=youruser

[Install]
WantedBy=multi-user.target
```

### 树莓派提示

树莓派 4 可流畅运行本服务（视觉分析在云端，本地只做取流与音频检测）。ffmpeg 用系统包 `sudo apt install ffmpeg`，并通过环境变量 `FFMPEG_PATH=/usr/bin/ffmpeg` 指定。

## 安全注意

- **不要**把 8080/1935 等端口映射到公网；本系统按纯局域网设计
- 修改 `server.access_token` 默认口令
- 启用云端视觉分析时，画面帧会发到所选模型服务商，介意者请将 `vision.provider` 设为 `disabled`
