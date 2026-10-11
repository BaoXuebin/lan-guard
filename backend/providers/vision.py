"""视觉分析 Provider 抽象层。

所有 Provider 都实现 `async analyze(jpeg: bytes) -> dict | None`，
返回统一结构的 JSON（解析失败或异常时返回 None）：
{
  "state": "<场景包 state_labels 中定义的状态>",
  "face_covered": bool,
  "awake": bool,
  "in_frame": bool,
  "description": "一句话描述"
}
提示词由场景包（scenes/*.yaml）提供，Provider 与具体场景解耦。
"""
import base64
import json

import httpx

from ..config import Config

# 场景包缺省时的兜底提示词（与 scenes/baby-sleep.yaml 保持一致）
PROMPT = """你是一名专业的婴儿睡眠看护助手。请仔细观察这张婴儿床监控画面，严格按以下 JSON 格式输出（不要输出任何其他文字）：
{
  "state": "supine",
  "face_covered": false,
  "awake": false,
  "in_frame": true,
  "description": "一句话描述"
}
- state：supine=仰卧, left_side=婴儿自身左侧卧, right_side=婴儿自身右侧卧, prone=趴卧, unknown=无法判断
- face_covered：口鼻是否被遮挡；awake：是否醒着；in_frame：画面中是否能看到婴儿
- description：不超过 30 字的中文描述"""


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    data["state"] = str(data.get("state") or "unknown")
    data["face_covered"] = bool(data.get("face_covered", False))
    data["awake"] = bool(data.get("awake", False))
    data["in_frame"] = bool(data.get("in_frame", True))
    data["description"] = str(data.get("description", ""))[:80]
    return data


class BaseProvider:
    name = "base"

    async def analyze(self, jpeg: bytes) -> dict | None:
        raise NotImplementedError

    async def close(self):
        pass


class ZhipuProvider(BaseProvider):
    """智谱 GLM 视觉模型（OpenAI 兼容接口）。"""

    name = "zhipu"

    def __init__(self, cfg: Config, prompt: str | None = None):
        v = cfg["vision"]
        self.client = httpx.AsyncClient(
            base_url=v["base_url"],
            headers={"Authorization": f"Bearer {cfg.vision_api_key}"},
            timeout=float(v["timeout_sec"]),
        )
        self.model = v["model"]
        self.prompt = prompt or PROMPT

    async def analyze(self, jpeg: bytes) -> dict | None:
        b64 = base64.b64encode(jpeg).decode()
        try:
            resp = await self.client.post(
                "/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image_url",
                             "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                            {"type": "text", "text": self.prompt},
                        ],
                    }],
                    "temperature": 0.1,
                    "max_tokens": 1024,
                    # glm-4.5v 等思考模型默认会先"思考"，max_tokens 常被思考耗尽导致
                    # content 为空；本任务只需结构化输出，直接关闭思考
                    "thinking": {"type": "disabled"},
                },
            )
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
            content = msg.get("content") or msg.get("reasoning_content") or ""
            data = _parse_json(content)
            if data is None:
                print(f"[{type(self).__name__}] 返回内容无法解析: {content[:200]!r}")
            return data
        except Exception as e:
            print(f"[{type(self).__name__}] 分析失败: {e}")
            return None


class OpenAICompatProvider(ZhipuProvider):
    """任何 OpenAI 兼容的视觉模型（Qwen-VL / GLM-4V-Flash / GPT-4o-mini ...），
    配置方式与 zhipu 相同，只是 base_url / model / key 不同。"""

    name = "openai_compat"


class MockProvider(BaseProvider):
    """调试用：不调用云端，返回固定结果。"""

    name = "mock"

    async def analyze(self, jpeg: bytes) -> dict | None:
        return {
            "posture": "supine",
            "face_covered": False,
            "awake": False,
            "in_frame": True,
            "description": "[mock] 婴儿仰卧安睡",
        }


class DisabledProvider(BaseProvider):
    name = "disabled"

    async def analyze(self, jpeg: bytes) -> dict | None:
        return None


def create_provider(cfg: Config, prompt: str | None = None) -> BaseProvider:
    name = cfg["vision"]["provider"]
    if name == "zhipu":
        if not cfg.vision_api_key:
            print("[Vision] 未配置 API Key，视觉分析已禁用（请检查 .env 或设置页）")
            return DisabledProvider()
        return ZhipuProvider(cfg, prompt)
    if name == "openai_compat":
        if not cfg.vision_api_key:
            print("[Vision] 未配置 API Key，视觉分析已禁用（请检查 .env 或设置页）")
            return OpenAICompatProvider(cfg, prompt)
        return OpenAICompatProvider(cfg, prompt)
    if name == "mock":
        return MockProvider()
    return DisabledProvider()
