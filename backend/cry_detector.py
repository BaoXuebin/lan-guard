"""哭声检测：本地启发式（响度 RMS + 持续时长 + 频率质心），不依赖云端。

原理：16bit PCM 按 50ms 窗算 RMS；滑动基线为近 N 秒环境噪声水平。
候选哭声 = RMS 同时高于绝对阈值与基线的若干倍；候选持续超过 min_sustain_sec
且频率质心落在婴儿哭声常见频段（约 300~1200Hz）即判定为哭声。
"""
import time

import numpy as np


class CryDetector:
    def __init__(self, cfg: dict, sample_rate: int):
        self.sample_rate = sample_rate
        self.cry_threshold_rms = float(cfg["cry_threshold_rms"])
        self.min_sustain_sec = float(cfg["min_sustain_sec"])
        self.baseline_window_sec = float(cfg["baseline_window_sec"])
        self.win_samples = int(sample_rate * 0.05)  # 50ms
        self._buf = np.empty(0, dtype=np.int16)
        self._win_rms: list[tuple[float, float, float]] = []  # (ts, rms, centroid)
        self._candidate_since: float | None = None

    def feed(self, pcm_bytes: bytes) -> bool:
        """喂入 PCM；若判定发生哭声返回 True（边沿触发，同一次哭声只返回一次）。"""
        data = np.frombuffer(pcm_bytes, dtype=np.int16)
        self._buf = np.concatenate([self._buf, data]) if self._buf.size else data

        now = time.time()
        detected = False
        while self._buf.size >= self.win_samples:
            win = self._buf[: self.win_samples].astype(np.float32)
            self._buf = self._buf[self.win_samples:]
            rms = float(np.sqrt(np.mean(win ** 2)))
            centroid = self._spectral_centroid(win)
            self._win_rms.append((now, rms, centroid))
            # 只保留基线窗口
            horizon = now - self.baseline_window_sec
            self._win_rms = [t for t in self._win_rms if t[0] >= horizon]

            baseline = float(np.median([r for _, r, _ in self._win_rms])) if self._win_rms else 0.0
            is_loud = rms > self.cry_threshold_rms and rms > max(baseline * 3.0, 200.0)
            freq_ok = 300.0 <= centroid <= 1500.0
            if is_loud and freq_ok:
                if self._candidate_since is None:
                    self._candidate_since = now
                elif now - self._candidate_since >= self.min_sustain_sec:
                    detected = True
                    self._candidate_since = None  # 同一次哭声只报一次
            else:
                self._candidate_since = None
        return detected

    @staticmethod
    def _spectral_centroid(win: np.ndarray) -> float:
        spec = np.abs(np.fft.rfft(win * np.hanning(win.size)))
        # 窗长固定为 50ms，故采样率 = N / 0.05
        freqs = np.fft.rfftfreq(win.size, d=0.05 / win.size)
        total = spec.sum()
        if total <= 0:
            return 0.0
        return float((spec * freqs).sum() / total)
