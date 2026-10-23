"""Gemerkte Entscheidungen (Ignorieren, offene Slack-Nachrichten) als JSON im Daten-Ordner."""
import json
import threading
from pathlib import Path

LOCK = threading.RLock()


class State:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "state.json"

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data.setdefault("ignored", {})
        data.setdefault("items", {})
        data.setdefault("last_issues", [])
        return data

    def save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
