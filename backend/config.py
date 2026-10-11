"""配置加载：config.yaml + .env（密钥）。"""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "scene": "scenes/baby-sleep.yaml",  # 场景包路径（相对项目根）
    "server": {"host": "0.0.0.0", "port": 8080, "access_token": "change-me",
               "https_port": 8443,
               "ssl_certfile": "deploy/cert/server.crt",
               "ssl_keyfile": "deploy/cert/server.key"},
    "stream": {
        "rtsp_url": "rtsp://127.0.0.1:8554/baby",
        "sample_interval": 5,
        "analyze_interval": 15,
        "idle_analyze_interval": 60,
        "motion_threshold": 8,
    },
    "vision": {
        "provider": "zhipu",
        "model": "glm-4.5v",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key": "",
        "api_key_env": "ZHIPU_API_KEY",
        "timeout_sec": 30,
        "dark_enhance": True,     # 夜间弱光：送分析前自动增亮暗帧
        "dark_threshold": 60,     # 平均亮度(0~255)低于该值视为暗帧
    },
    "audio": {
        "enabled": True,
        "sample_rate": 16000,
        "cry_threshold_rms": 500,
        "min_sustain_sec": 1.5,
        "baseline_window_sec": 30,
    },
    "alerts": {
        "side_sleep_minutes": 30,
        "side_cooldown_minutes": 15,
        "prone_alert": True,
        "face_cover_alert": True,
        "anomaly_cooldown_sec": 120,
        "away_grace_sec": 20,
        "cry_cooldown_sec": 60,
    },
    "storage": {"events_file": "data/events.jsonl"},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, path: Path | None = None):
        load_dotenv(PROJECT_ROOT / ".env")
        data = {}
        env_path = os.environ.get("BM_CONFIG")
        cfg_path = path or (Path(env_path) if env_path else PROJECT_ROOT / "config.yaml")
        if cfg_path.is_file():
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        self._data = _deep_merge(DEFAULTS, data)
        self.path = cfg_path

    def __getitem__(self, key):
        return self._data[key]

    @property
    def vision_api_key(self) -> str:
        # 优先用前端/配置文件里保存的 Key，留空则回退到 .env 环境变量
        cfg_key = str(self._data["vision"].get("api_key") or "").strip()
        if cfg_key:
            return cfg_key
        env_name = self._data["vision"]["api_key_env"]
        return os.environ.get(env_name, "")

    @property
    def ffmpeg_path(self) -> str:
        return os.environ.get(
            "FFMPEG_PATH", str(PROJECT_ROOT / "tools/bin/ffmpeg-7.1.1-essentials_build/bin/ffmpeg.exe")
        )
