import json
from datetime import datetime, timezone
from pathlib import Path


class MetricsLogger:
    def __init__(self, log_path: Path, *, room: str | None, room_id: str | None, job_id: str | None, agent_name: str) -> None:
        self._log_path = log_path
        self._room = room
        self._room_id = room_id
        self._job_id = job_id
        self._agent_name = agent_name

    def append(self, event_name: str, payload: dict) -> None:
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_name,
            "room": self._room,
            "room_id": self._room_id,
            "job_id": self._job_id,
            "agent_name": self._agent_name,
            "payload": payload,
        }
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

