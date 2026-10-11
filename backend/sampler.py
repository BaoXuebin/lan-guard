"""流采样器：用两个常驻 ffmpeg 进程从 MediaMTX 的 RTSP 流中
1) 按固定间隔抽 JPEG 帧（供运动检测与视觉分析）
2) 抽 16bit 单声道 PCM（供哭声检测）

任一进程退出后自动重启（指数退避），推流端（iPhone）掉线重连后自动恢复。
"""
import asyncio
import subprocess
import time
from pathlib import Path

from .config import Config

# JPEG 流分隔标记
_SOI = b"\xff\xd8\xff"
_EOI = b"\xff\xd9"


class StreamSampler:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.ffmpeg = cfg.ffmpeg_path
        self.rtsp_url: str = cfg["stream"]["rtsp_url"]
        self.sample_interval: float = float(cfg["stream"]["sample_interval"])

        self.frame_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=8)
        self.pcm_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)

        self._video_proc: subprocess.Popen | None = None
        self._audio_proc: subprocess.Popen | None = None
        self._running = False
        self.stream_ok = False
        self.last_frame_ts: float = 0.0

    # ---------------- 内部：启动 ffmpeg ----------------

    def _video_cmd(self) -> list[str]:
        return [
            self.ffmpeg, "-loglevel", "error",
            "-rtsp_transport", "tcp",
            "-i", self.rtsp_url,
            "-vf", f"fps=1/{self.sample_interval:g}",
            "-an", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
        ]

    def _audio_cmd(self) -> list[str]:
        rate = int(self.cfg["audio"]["sample_rate"])
        return [
            self.ffmpeg, "-loglevel", "error",
            "-rtsp_transport", "tcp",
            "-i", self.rtsp_url,
            "-vn", "-acodec", "pcm_s16le", "-ar", str(rate), "-ac", "1",
            "-f", "s16le", "pipe:1",
        ]

    async def _pump_video(self):
        backoff = 2
        while self._running:
            try:
                self._video_proc = subprocess.Popen(
                    self._video_cmd(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                )
                buf = b""
                proc = self._video_proc
                while self._running and proc.poll() is None:
                    chunk = await asyncio.get_event_loop().run_in_executor(
                        None, proc.stdout.read, 65536
                    )
                    if not chunk:
                        break
                    buf += chunk
                    # 按 SOI/EOI 切出完整 JPEG
                    while True:
                        start = buf.find(_SOI)
                        if start < 0:
                            buf = b""
                            break
                        end = buf.find(_EOI, start + 3)
                        if end < 0:
                            if start > 0:
                                buf = buf[start:]
                            break
                        jpeg = buf[start:end + 2]
                        buf = buf[end + 2:]
                        if len(jpeg) < 2000:  # 过滤残帧
                            continue
                        self.last_frame_ts = time.time()
                        self.stream_ok = True
                        if self.frame_queue.full():
                            try:
                                self.frame_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                        await self.frame_queue.put(jpeg)
                self.stream_ok = False
                backoff = 2
            except Exception as e:
                print(f"[Sampler] 视频管道异常: {e}")
            if self._running:
                print(f"[Sampler] 视频流中断，{backoff}s 后重连 {self.rtsp_url}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _pump_audio(self):
        backoff = 2
        while self._running:
            try:
                self._audio_proc = subprocess.Popen(
                    self._audio_cmd(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
                )
                proc = self._audio_proc
                while self._running and proc.poll() is None:
                    chunk = await asyncio.get_event_loop().run_in_executor(
                        None, proc.stdout.read, 3200 * 2  # 0.2s @16k mono s16
                    )
                    if not chunk:
                        break
                    if self.pcm_queue.full():
                        try:
                            self.pcm_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    await self.pcm_queue.put(chunk)
            except Exception as e:
                print(f"[Sampler] 音频管道异常: {e}")
            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    # ---------------- 生命周期 ----------------

    def start(self):
        self._running = True
        asyncio.get_event_loop().create_task(self._pump_video())
        if self.cfg["audio"]["enabled"]:
            asyncio.get_event_loop().create_task(self._pump_audio())

    def stop(self):
        self._running = False
        for p in (self._video_proc, self._audio_proc):
            if p and p.poll() is None:
                p.kill()
