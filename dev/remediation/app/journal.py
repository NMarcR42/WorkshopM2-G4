"""Journal d'incidents sur disque (volume) : survit à un redémarrage du moteur et alimente la supervision.

Un dossier par incident : incident.json (état + chronologie) et <action>.json (contrat de l'interface (b)).
"""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, data: dict) -> None:
    # Écriture atomique : un lecteur (dashboard) ne voit jamais un fichier à moitié écrit.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    os.replace(tmp, path)


class Journal:
    def __init__(self, root: str):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.incidents: dict[str, dict] = {}
        self.root.mkdir(parents=True, exist_ok=True)
        for f in self.root.glob("*/incident.json"):
            try:
                inc = json.loads(f.read_text())
            except (OSError, ValueError):
                continue  # un fichier corrompu ne doit pas empêcher le moteur de démarrer
            if inc.get("status") == "IN_PROGRESS":
                # Le moteur s'est arrêté en pleine réparation : on ne sait pas si elle a abouti.
                inc["status"] = "UNRESOLVED"
                inc["timeline"].append({"ts": now(), "event": "interrupted", "detail": "moteur redémarré en cours d'incident"})
                write_json(f, inc)
            self.incidents[inc["id"]] = inc

    def create(self, signal: dict) -> dict:
        inc = {
            "id": str(uuid.uuid4()),
            "anomaly_id": signal["anomaly_id"],
            "status": "IN_PROGRESS",
            "target_service": signal["target_service"],
            "created_at": now(),
            "ended_at": None,
            "resolved_by": None,
            "signal": signal,
            "timeline": [],
        }
        with self.lock:
            self.incidents[inc["id"]] = inc
            self._save(inc)
        return inc

    def add(self, inc: dict, name: str, **fields) -> None:
        with self.lock:
            inc["timeline"].append({"ts": now(), "event": name, **fields})
            self._save(inc)

    def finish(self, inc: dict, status: str, resolved_by: str | None) -> None:
        with self.lock:
            inc.update(status=status, resolved_by=resolved_by, ended_at=now())
            self._save(inc)

    def write_action(self, inc_id: str, action: str, record: dict) -> None:
        write_json(self.root / inc_id / f"{action}.json", record)

    def by_anomaly(self, anomaly_id: str) -> dict | None:
        with self.lock:
            return next((i for i in self.incidents.values() if i["anomaly_id"] == anomaly_id), None)

    def active(self) -> dict | None:
        with self.lock:
            return next((i for i in self.incidents.values() if i["status"] == "IN_PROGRESS"), None)

    def recent(self, limit: int) -> list[dict]:
        with self.lock:
            return sorted(self.incidents.values(), key=lambda i: i["created_at"], reverse=True)[:limit]

    def _save(self, inc: dict) -> None:
        write_json(self.root / inc["id"] / "incident.json", inc)
