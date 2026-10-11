"""场景包加载：scenes/*.yaml = 视觉提示词 + 状态标签 + 告警规则。"""
from pathlib import Path

import yaml

from .config import PROJECT_ROOT

REQUIRED_KEYS = ("name", "vision_prompt", "state_labels")


def scenes_dir() -> Path:
    return PROJECT_ROOT / "scenes"


def list_scenes() -> list[dict]:
    """列出所有可用场景（文件名 + 名称 + 描述）。"""
    out = []
    for f in sorted(scenes_dir().glob("*.yaml")):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            out.append({"file": f.name, "name": data.get("name", f.stem),
                        "description": data.get("description", "")})
        except yaml.YAMLError as e:
            print(f"[scenes] 场景文件损坏: {f.name}: {e}")
    return out


def load_scene(cfg) -> dict:
    """按 config 的 scene 路径加载场景包，附上 file 字段。"""
    rel = cfg._data.get("scene", "scenes/baby-sleep.yaml")
    path = (cfg.path.parent / rel).resolve()
    if not path.is_file():
        print(f"[scenes] 场景文件不存在: {path}，回退默认 baby-sleep")
        path = scenes_dir() / "baby-sleep.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"场景 {path.name} 缺少字段: {missing}")
    data["file"] = path.name
    print(f"[scenes] 已加载场景: {data['name']} ({path.name})")
    return data
