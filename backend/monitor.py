"""监控主逻辑（场景驱动）：运动检测 → 视觉分析调度 → 告警状态机 → 事件产出。

告警规则、状态标签、提示词全部来自"场景包"（scenes/*.yaml），
引擎本身与具体被监护对象（婴儿/老人/宠物...）解耦。
"""
import asyncio
import io
import time

import numpy as np
from PIL import Image, ImageEnhance

from .config import Config
from .cry_detector import CryDetector
from .events import EventStore
from .providers import BaseProvider
from .sampler import StreamSampler

DEFAULT_TEXTS = {
    "state_change": "状态变化：{prev} → {cur}",
    "awake": "对象醒了",
    "asleep": "对象似乎睡着了",
}


def motion_score(prev_gray: np.ndarray | None, jpeg: bytes) -> tuple[float, np.ndarray]:
    """相邻帧平均绝对差（0~100），用于自适应降频。"""
    img = Image.open(io.BytesIO(jpeg)).convert("L").resize((64, 48))
    gray = np.asarray(img, dtype=np.float32)
    if prev_gray is None or prev_gray.shape != gray.shape:
        return 100.0, gray
    return float(np.mean(np.abs(gray - prev_gray)) / 255.0 * 100.0), gray


def enhance_if_dark(jpeg: bytes, cfg: Config) -> bytes:
    """夜间弱光增强：平均亮度低于阈值时做亮度/对比度增强后再送大模型。

    全黑画面（无任何信息）增强也无济于事，但夜灯下的昏暗画面可显著提升
    模型可辨识度。
    """
    if not cfg["vision"].get("dark_enhance", True):
        return jpeg
    img = Image.open(io.BytesIO(jpeg))
    gray = np.asarray(img.convert("L"), dtype=np.float32)
    mean = float(gray.mean())
    threshold = float(cfg["vision"].get("dark_threshold", 60))
    if mean >= threshold or mean < 1.0:  # <1.0 近乎全黑，增亮无意义
        return jpeg
    # 增亮幅度按暗的程度自适应，目标拉到阈值之上
    factor = min(3.5, max(1.6, threshold / max(mean, 5.0) * 1.4))
    img = ImageEnhance.Brightness(img).enhance(factor)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=85)
    return out.getvalue()


class BabyMonitor:
    def __init__(self, cfg: Config, events: EventStore, sampler: StreamSampler,
                 provider: BaseProvider, scene: dict):
        self.cfg = cfg
        self.events = events
        self.sampler = sampler
        self.provider = provider
        self.scene = scene
        self.cry_detector = CryDetector(cfg["audio"], int(cfg["audio"]["sample_rate"])) \
            if cfg["audio"]["enabled"] else None

        # 状态
        self.state = {
            "scene_name": scene.get("name", ""),
            "state": "unknown",
            "state_label": "未知",
            "state_since": None,
            "state_minutes": 0.0,
            "awake": False,
            "crying": False,
            "face_covered": False,
            "in_frame": True,
            "stream_ok": False,
            "motion": 0.0,
            "last_analysis_ts": None,
            "last_description": "",
            "vision_provider": provider.name,
        }
        self._last_alert: dict[str, float] = {}
        self._running = False

    # ---------------- 工具 ----------------

    def _cooldown_ok(self, key: str, seconds: float) -> bool:
        now = time.time()
        if now - self._last_alert.get(key, 0) >= seconds:
            self._last_alert[key] = now
            return True
        return False

    def _label(self, state: str) -> str:
        return self.scene["state_labels"].get(state, self.scene["state_labels"].get("unknown", state))

    def _set_state(self, state: str, description: str):
        prev = self.state["state"]
        now = time.time()
        self.state["state"] = state
        self.state["state_label"] = self._label(state)
        self.state["state_since"] = now
        self.state["last_description"] = description
        if state != prev:
            texts = {**DEFAULT_TEXTS, **self.scene.get("texts", {})}
            self.events.add("state_change", "info",
                            texts["state_change"].format(prev=self._label(prev),
                                                         cur=self._label(state)),
                            {"from": prev, "to": state, "desc": description})

    # ---------------- 告警规则（来自场景包） ----------------

    def _check_alerts(self):
        rules = self.scene.get("rules", {})
        now = time.time()
        since = self.state["state_since"]

        # 1. 状态停留过久 → 提醒（换边/翻身等）
        d = rules.get("duration_alert") or {}
        if d and self.state["state"] in d.get("states", []) and since:
            minutes = (now - since) / 60
            self.state["state_minutes"] = round(minutes, 1)
            if minutes >= float(d["minutes"]):
                if self._cooldown_ok("duration", float(d.get("cooldown_minutes", 15)) * 60):
                    self.events.add("duration", "warning",
                                    d["template"].format(label=self.state["state_label"],
                                                         minutes=int(minutes)))
        else:
            self.state["state_minutes"] = 0.0

        # 2. 立即告警状态（趴睡/跌倒等）
        ia = rules.get("immediate_alert") or {}
        if ia and self.state["state"] in ia.get("states", []):
            if self._cooldown_ok("immediate", float(ia.get("cooldown_seconds", 120))):
                self.events.add("immediate", "alert",
                                ia["template"].format(label=self.state["state_label"]))

        # 3. 模型布尔标志 → 告警（如口鼻遮挡）
        fa = (rules.get("flag_alerts") or {}).get("face_covered") or {}
        if fa.get("enabled") and self.state["face_covered"]:
            if self._cooldown_ok("face_covered", float(fa.get("cooldown_seconds", 120))):
                self.events.add("flag", "alert",
                                fa.get("template", "口鼻可能被遮挡，请立即查看"))

        # 4. 离开画面
        away = rules.get("away") or {}
        if not self.state["in_frame"]:
            if self._cooldown_ok("away", float(away.get("grace_seconds", 20))):
                self.events.add("away", "warning",
                                away.get("template", "画面中看不到对象了，请检查情况"))

    # ---------------- 视觉分析循环 ----------------

    async def _vision_loop(self):
        prev_gray: np.ndarray | None = None
        last_analyzed = 0.0
        last_motion = 100.0  # 启动时先分析一次

        while self._running:
            try:
                jpeg = await asyncio.wait_for(self.sampler.frame_queue.get(), timeout=10)
            except asyncio.TimeoutError:
                self.state["stream_ok"] = self.sampler.stream_ok
                continue

            self.state["stream_ok"] = self.sampler.stream_ok
            score, prev_gray = motion_score(prev_gray, jpeg)
            self.state["motion"] = round(score, 1)
            last_motion = score

            # 每轮实时读取，使"设置"页保存的参数立即生效
            s = self.cfg["stream"]
            analyze_interval = float(s["analyze_interval"])
            idle_interval = float(s["idle_analyze_interval"])
            motion_threshold = float(s["motion_threshold"])

            now = time.time()
            due = now - last_analyzed >= (idle_interval if last_motion < motion_threshold
                                          else analyze_interval)
            if not due:
                continue
            last_analyzed = now

            if self.provider.name == "disabled":
                continue
            result = await self.provider.analyze(enhance_if_dark(jpeg, self.cfg))
            self.state["last_analysis_ts"] = now
            if not result:
                continue

            texts = {**DEFAULT_TEXTS, **self.scene.get("texts", {})}

            # 醒/睡判定
            if result["awake"] and not self.state["awake"]:
                self.events.add("awake", "info", texts["awake"])
            elif not result["awake"] and self.state["awake"]:
                self.events.add("asleep", "info", texts["asleep"])
            self.state["awake"] = result["awake"]
            self.state["face_covered"] = result["face_covered"]
            self.state["in_frame"] = result["in_frame"]
            # 模型返回的状态必须是场景定义过的，否则视为未知
            state = result["state"] if result["state"] in self.scene["state_labels"] else "unknown"
            self._set_state(state, result["description"])
            self._check_alerts()

    # ---------------- 哭声/声音检测循环 ----------------

    async def _audio_loop(self):
        while self._running:
            try:
                pcm = await asyncio.wait_for(self.sampler.pcm_queue.get(), timeout=10)
            except asyncio.TimeoutError:
                continue
            audio = (self.scene.get("rules") or {}).get("audio_alert") or {}
            if self.cry_detector and self.cry_detector.feed(pcm):
                self.state["crying"] = True
                self.state["awake"] = True
                if self._cooldown_ok("audio", float(audio.get("cooldown_seconds", 60))):
                    self.events.add("audio", "alert",
                                    audio.get("template", "检测到哭声/呼喊声！"))
                asyncio.get_event_loop().call_later(
                    10.0, lambda: self.state.update(crying=False))

    def set_provider(self, provider: BaseProvider):
        """热切换视觉分析 Provider（"设置"页保存后调用）。"""
        old = self.provider
        self.provider = provider
        self.state["vision_provider"] = provider.name
        try:
            asyncio.get_event_loop().create_task(old.close())
        except RuntimeError:
            pass
        self.events.add("monitor", "info", f"视觉分析已切换为: {provider.name}")

    def set_scene(self, scene: dict):
        """热切换场景包：提示词经 set_provider 生效，规则/标签立即生效。"""
        self.scene = scene
        self.state["scene_name"] = scene.get("name", "")
        self.state["state"] = "unknown"
        self.state["state_label"] = self._label("unknown")
        self.state["state_since"] = time.time()
        self.events.add("monitor", "info", f"已切换场景: {scene.get('name', '')}")

    # ---------------- 生命周期 ----------------

    def start(self):
        self._running = True
        self.sampler.start()
        loop = asyncio.get_event_loop()
        loop.create_task(self._vision_loop())
        if self.cry_detector:
            loop.create_task(self._audio_loop())
        self.events.add("monitor", "info",
                        f"监控服务已启动（场景: {self.scene.get('name', '')}）")

    def stop(self):
        self._running = False
        self.sampler.stop()
        try:
            asyncio.get_event_loop().create_task(self.provider.close())
        except RuntimeError:
            pass
