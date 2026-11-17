"""One audit format for the orchestrator (END_TO_END_ITSM.md §7.6): one JSON object per line, append-only."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT_FILE = ROOT / "var" / "audit.jsonl"

FIELDS = ("run_id", "case_id", "practice", "node", "identity", "action", "record", "rule", "criteria", "result",
          "decided_by", "before_image", "model", "tokens", "harmful")


class Audit:
    def __init__(self, path: Path | None = None, run_id: str = "") -> None:
        self.path = path or AUDIT_FILE
        self.run_id = run_id
        self.rows: list[dict] = []  # kept in memory too, so a probe run can check its own entries

    def write(self, **kw) -> dict:
        unknown = set(kw) - set(FIELDS)
        if unknown:
            raise ValueError(f"unknown audit fields {sorted(unknown)}")
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "id": uuid.uuid4().hex,
               "run_id": self.run_id, **kw}
        self.rows.append(row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        return row
