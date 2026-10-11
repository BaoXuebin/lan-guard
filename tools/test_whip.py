"""WHIP 推流测试客户端：不用 iPhone 也能验证整条 WebRTC 链路。

用法:
  .venv/Scripts/pip install aiortc   # 测试工具专用依赖，运行主服务不需要
  .venv/Scripts/python tools/test_whip.py [whip地址] [秒数]
默认推到 https://127.0.0.1:8889/baby/whip，推 15 秒后退出。
发布内容: 流动彩条视频 + 440Hz 正弦音频。
"""
import asyncio
import sys
import time
from pathlib import Path

import av
import numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack, AudioStreamTrack

PROJECT = Path(__file__).resolve().parent.parent
CA = PROJECT / "deploy/cert/ca.crt"


class ColorBars(VideoStreamTrack):
    def __init__(self):
        super().__init__()
        self._ts = 0

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        frame = av.VideoFrame(640, 480, format="rgb24")
        img = frame.to_ndarray()
        self._ts += 1
        img[:, :, 0] = (self._ts * 5) % 255  # 流动的红色通道，便于肉眼区分
        img[:, 160:320, 1] = 200
        frame = av.VideoFrame.from_ndarray(img, format="rgb24")
        frame.pts = pts
        frame.time_base = time_base
        await asyncio.sleep(1 / 15)
        return frame


class Tone(AudioStreamTrack):
    def __init__(self):
        super().__init__()
        self._ts = 0

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        samples = 960  # 20ms @48k
        t = (np.arange(samples) + self._ts) / 48000
        self._ts += samples
        pcm = (np.sin(2 * np.pi * 440 * t) * 8000).astype(np.int16)
        frame = av.AudioFrame.from_ndarray(pcm.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = 48000
        frame.pts = pts
        frame.time_base = time_base
        return frame


async def main(url: str, duration: float):
    pc = RTCPeerConnection()
    pc.addTrack(ColorBars())
    pc.addTrack(Tone())

    @pc.on("connectionstatechange")
    async def on_state():
        print("[whip-test] 连接状态:", pc.connectionState)

    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    print("[whip-test] SDP offer 已生成，POST 到", url)

    import httpx
    ssl_ctx = None
    if url.startswith("https"):
        import ssl as _ssl
        ssl_ctx = _ssl.create_default_context(cafile=str(CA))
    async with httpx.AsyncClient(verify=ssl_ctx, timeout=15) as client:
        resp = await client.post(url, content=pc.localDescription.sdp,
                                 headers={"Content-Type": "application/sdp"})
        print("[whip-test] WHIP 响应:", resp.status_code)
        if resp.status_code != 201:
            print(resp.text[:300])
            return
        await pc.setRemoteDescription(RTCSessionDescription(sdp=resp.text, type="answer"))

    await asyncio.sleep(duration)
    await pc.close()
    print("[whip-test] 测试结束")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://127.0.0.1:8889/baby/whip"
    asyncio.run(main(url, 15.0 if len(sys.argv) < 3 else float(sys.argv[2])))
