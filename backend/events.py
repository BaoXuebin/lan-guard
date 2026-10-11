"""事件与状态存储：内存态 + JSONL 落盘。"""
import json
import threading
import time
from collections import deque
from pathlib import Path


class EventStore:
    def __init__(self, events_file: str, max_in_memory: int = 500):
        self.file = Path(events_file)
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._events: deque[dict] = deque(maxlen=max_in_memory)
        self._subscribers: list = []  # asyncio queues，由 main.py 注册

    def add(self, kind: str, level: str, message: str, detail: dict | None = None):
        event = {
            "ts": time.time(),
            "kind": kind,
            "level": level,  # info | warning | alert
            "message": message,
            "detail": detail or {},
        }
        with self._lock:
            self._events.appendleft(event)
            try:
                with self.file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
            except OSError as e:
                print(f"[EventStore] 写日志失败: {e}")
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except Exception:
                pass
        return event

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(self._events)[:limit]

    def subscribe(self, queue) -> None:
        self._subscribers.append(queue)

    def unsubscribe(self, queue) -> None:
        if queue in self._subscribers:
            self._subscribers.remove(queue)
