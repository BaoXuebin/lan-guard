"""FastAPI 入口：REST + WebSocket + 静态网页 + WHIP/WHEP 同源代理，带简单口令鉴权。"""
import asyncio
import pathlib
import time

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import Config
from .events import EventStore
from .monitor import BabyMonitor
from .providers import create_provider
from .scenes import list_scenes, load_scene, scenes_dir
from .sampler import StreamSampler

WEB_DIR = pathlib.Path(__file__).resolve().parent.parent / "web"

app = FastAPI(title="lan-guard")
cfg = Config()
events = EventStore(cfg["storage"]["events_file"])
sampler = StreamSampler(cfg)
scene = load_scene(cfg)
cfg.scene_dict = scene
provider = create_provider(cfg, prompt=scene["vision_prompt"])
monitor = BabyMonitor(cfg, events, sampler, provider, scene)

_started = False


@app.on_event("startup")
async def startup():
    global _started
    if not _started:
        monitor.start()
        _started = True


@app.on_event("shutdown")
async def shutdown():
    monitor.stop()
    await provider.close()


def _check_token(token: str):
    if token != cfg["server"]["access_token"]:
        raise HTTPException(status_code=401, detail="访问口令错误")


# ---------------- REST ----------------

@app.get("/api/health")
async def health():
    return {"ok": True, "ts": time.time()}


@app.get("/api/status")
async def status(token: str = Query("")):
    _check_token(token)
    return monitor.state


@app.get("/api/events")
async def get_events(limit: int = 50, token: str = Query("")):
    _check_token(token)
    return events.recent(min(limit, 200))


@app.get("/api/config")
async def get_public_config(request: Request, token: str = Query("")):
    """给前端用的少量公开配置（不含任何密钥）。"""
    _check_token(token)
    host = cfg["stream"]["rtsp_url"].split("//")[1].split(":")[0]
    https_port = int(cfg["server"].get("https_port", 0) or 0)
    lan_ip = request.url.hostname  # 用访问者请求的地址生成二维码，天然适配 IP 变更
    return {
        "whep_url": "/proxy/whep",  # 同源代理，相对路径
        "hls_url": f"http://{host}:8888/baby/index.m3u8",
        "https_enabled": https_port > 0,
        "ca_url": f"http://{lan_ip}:{int(cfg['server']['port'])}/ca.crt",
        "push_url": f"https://{lan_ip}:{https_port}/push" if https_port else "",
    }


# ---------------- WHIP/WHEP 同源代理 ----------------
# 浏览器只需访问后端自身的 8080/8443 端口，由后端转发 SDP 到本机 MediaMTX。
# 这样手机无需信任 MediaMTX(8889) 的证书——iOS 上"点了开始没反应"的最大故障源。

_mediamtx_client: httpx.AsyncClient | None = None


def _mediamtx_base() -> str:
    host = cfg["stream"]["rtsp_url"].split("//")[1].split(":")[0]
    return f"http://{host}:8889"


async def _proxy_sdp(request: Request, endpoint: str) -> Response:
    global _mediamtx_client
    if _mediamtx_client is None:
        _mediamtx_client = httpx.AsyncClient(timeout=30)
    body = await request.body()
    try:
        resp = await _mediamtx_client.post(
            f"{_mediamtx_base()}{endpoint}",
            content=body, headers={"Content-Type": "application/sdp"})
    except httpx.HTTPError as e:
        raise HTTPException(502, f"MediaMTX 不可达: {e}")
    return Response(resp.text, status_code=resp.status_code, media_type="application/sdp")


@app.post("/proxy/whip")
async def proxy_whip(request: Request):
    """推流端 SDP 交换（推流页 → MediaMTX）。"""
    return await _proxy_sdp(request, "/baby/whip")


@app.post("/proxy/whep")
async def proxy_whep(request: Request):
    """查看端 SDP 交换（监控页 → MediaMTX）。"""
    return await _proxy_sdp(request, "/baby/whep")


# ---------------- 设置（前端配置 + 持久化） ----------------

# 允许通过网页修改的字段白名单（其余只能改配置文件；告警阈值由场景包定义）
EDITABLE = {
    "server": {"access_token"},
    "stream": {"rtsp_url", "sample_interval", "analyze_interval",
               "idle_analyze_interval", "motion_threshold"},
    "vision": {"provider", "model", "base_url", "api_key", "timeout_sec",
               "dark_enhance", "dark_threshold"},
    "audio": {"enabled", "sample_rate", "cry_threshold_rms",
              "min_sustain_sec", "baseline_window_sec"},
}
RESTART_REQUIRED_KEYS = {("stream", "rtsp_url")}


@app.get("/api/settings")
async def get_settings(token: str = Query("")):
    _check_token(token)
    return cfg._data


@app.get("/api/scenes")
async def get_scenes(token: str = Query("")):
    """列出可用场景包。"""
    _check_token(token)
    return {"current": cfg._data.get("scene"), "scenes": list_scenes()}


@app.post("/api/settings")
async def post_settings(request: Request, token: str = Query("")):
    """保存设置：写入内存（立即生效）+ 持久化到 config.yaml。

    vision 配置变化时热切换 Provider；rtsp_url 变化需重启服务。
    """
    _check_token(token)
    body = await request.json()

    # 场景包切换（顶层键，热重载提示词与规则）
    scene_changed = False
    if "scene" in body:
        rel = str(body.pop("scene"))
        target = (cfg.path.parent / rel).resolve()
        if not target.is_file() or scenes_dir().resolve() not in target.parents:
            raise HTTPException(400, f"未知场景包: {rel}")
        cfg._data["scene"] = rel
        cfg.scene_dict = load_scene(cfg)
        monitor.set_scene(cfg.scene_dict)
        scene_changed = True

    # 校验
    restart_required = False
    vision_changed = scene_changed  # 场景变了 → 提示词变了 → 需重建 Provider
    for section, keys in (body or {}).items():
        if section not in EDITABLE or not isinstance(keys, dict):
            raise HTTPException(400, f"不支持的配置段: {section}")
        for key, value in keys.items():
            if key not in EDITABLE[section]:
                raise HTTPException(400, f"不支持修改: {section}.{key}")
            if (section, key) in RESTART_REQUIRED_KEYS and cfg._data[section].get(key) != value:
                restart_required = True
            if section == "vision":
                vision_changed = True
            if key in ("sample_interval", "analyze_interval", "idle_analyze_interval",
                       "motion_threshold", "timeout_sec", "sample_rate",
                       "cry_threshold_rms", "min_sustain_sec", "baseline_window_sec",
                       "dark_threshold"):
                try:
                    value = float(value) if "." in str(value) else int(value)
                except (TypeError, ValueError):
                    raise HTTPException(400, f"{section}.{key} 需要是数字")
            if key in ("enabled", "dark_enhance"):
                value = bool(value)
            cfg._data[section][key] = value

    # 持久化：保留原文件备份后整体写回（注释会丢失，见 README 说明）
    import yaml
    try:
        if cfg.path.is_file():
            backup = cfg.path.with_suffix(".yaml.bak")
            backup.write_text(cfg.path.read_text(encoding="utf-8"), encoding="utf-8")
        cfg.path.write_text(
            yaml.safe_dump(cfg._data, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    except OSError as e:
        raise HTTPException(500, f"写入配置文件失败: {e}")

    if vision_changed:
        monitor.set_provider(create_provider(cfg, prompt=cfg.scene_dict["vision_prompt"]))

    return {"ok": True, "restart_required": restart_required,
            "scene": cfg._data.get("scene")}


# ---------------- WebSocket（实时状态 + 事件推送） ----------------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, token: str = Query("")):
    if token != cfg["server"]["access_token"]:
        await ws.close(code=4401)
        return
    await ws.accept()
    queue: asyncio.Queue = asyncio.Queue()
    events.subscribe(queue)
    try:
        while True:
            payload = {"type": "status", "data": monitor.state}
            try:
                event = queue.get_nowait()
                payload = {"type": "event", "data": event}
            except asyncio.QueueEmpty:
                pass
            await ws.send_json(payload)
            await asyncio.sleep(1.0)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        events.unsubscribe(queue)


# ---------------- 静态页面 ----------------

@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/push")
async def push():
    """浏览器推流端（iOS Safari 需经 HTTPS 访问本页）。"""
    return FileResponse(WEB_DIR / "push.html")


@app.get("/sources")
async def sources():
    """注册推送源：扫码完成证书安装与推流页跳转。"""
    return FileResponse(WEB_DIR / "sources.html")


@app.get("/settings")
async def settings_page():
    """设置页：网页端修改配置并持久化。"""
    return FileResponse(WEB_DIR / "settings.html")


@app.get("/ca.crt")
async def ca_crt():
    """提供本地 CA 证书下载，供 iPhone 安装信任。"""
    cert = cfg.path.parent / "deploy/cert/ca.crt"
    if not cert.is_file():
        raise HTTPException(404, "证书不存在，请先运行 tools/make_certs.sh")
    return FileResponse(cert, media_type="application/x-x509-ca-cert",
                        filename="lan-guard-ca.crt")


app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
