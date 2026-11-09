"""Local record of deadline watches, because the Monitor API has no run-history endpoint."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


def default_store_path() -> Path:
    base = os.environ.get("CFP_SCOUT_HOME")
    return (Path(base) if base else Path.home() / ".cfp-scout") / "watches.json"


@dataclass
class WatchRecord:
    monitor_id: str
    conference_name: str
    url: str
    schedule_cron: str
    baseline_lines: list[str]
    baseline_captured_at: str


class WatchStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_store_path()

    def _load(self) -> dict[str, WatchRecord]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {key: WatchRecord(**value) for key, value in raw.items()}

    def _save(self, records: dict[str, WatchRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({key: asdict(value) for key, value in records.items()}, indent=2)
        handle, temp_name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as temp:
            temp.write(payload)
        os.replace(temp_name, self.path)

    def get(self, monitor_id: str) -> WatchRecord | None:
        return self._load().get(monitor_id)

    def put(self, record: WatchRecord) -> None:
        records = self._load()
        records[record.monitor_id] = record
        self._save(records)

    def delete(self, monitor_id: str) -> None:
        records = self._load()
        if records.pop(monitor_id, None) is not None:
            self._save(records)
