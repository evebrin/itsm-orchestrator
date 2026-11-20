"""pm-agent adapter (INTEGRATION_CONTRACT_pm-agent.md): pm-agent's functions run unchanged on the combined world.

pm-agent's own assumptions that do not hold here, and how this adapter answers them:
- its SNClient reads its own .env: pm-agent gets `View`, an object with the same methods (get_all, get, count,
  create, update), backed by the orchestrator's audited, dry-run-capable client and identity;
- its CIs carry the run tag: Larkspur CIs belong to the change repository's seed and are not tagged, so
  `world()` builds pm-agent's (all_incidents, cis) from the CIs the run's incidents name;
- incidents are linked to a problem through `incident.parent`: in a dry run that link is only planned, so `View`
  answers `parent=<planned problem>` from the planned links;
- its config/instance.json and runs/ live in its working copy: `use()` points them at files under var/.
"""
from __future__ import annotations

import json
import re
from contextlib import contextmanager
from pathlib import Path

from itsm import vendor_paths
from itsm.platform.settings import ROOT
from itsm.platform.sn import SNClient

CHOICES = ["incident.state", "incident.close_code", "problem.state", "problem.resolution_code", "change_request.state",
           "change_request.type", "change_request.risk", "change_request.impact", "kb_knowledge.workflow_state"]
PARENT = re.compile(r"^parent=([\w-]+)$")


def instance_file(sn: SNClient, path: Path = ROOT / "var" / "pm_instance.json") -> Path:
    """pm-agent's config/instance.json for this instance: choice values and labels, read only."""
    choices = {}
    for field in CHOICES:
        table, element = field.split(".")
        rows = sn.list("sys_choice", f"name={table}^element={element}^inactive=false", ["value", "label", "sequence"],
                       purpose=f"metadata: choices {field}", limit=200)
        if not rows and table != "incident":   # inherited from task
            rows = sn.list("sys_choice", f"name=task^element={element}^inactive=false", ["value", "label", "sequence"],
                           purpose=f"metadata: choices task.{element}", limit=200)
        choices[field] = [{"value": r["value"], "label": r["label"]} for r in rows]
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"choices": choices}, indent=1))
    return path


@contextmanager
def use(instance: Path, runs: Path = ROOT / "var" / "pm-runs"):
    """Import pm-agent with its config pointed at the orchestrator's files; restore afterwards."""
    vendor_paths.activate()
    import config as pm_config

    saved = pm_config.INSTANCE_FILE, pm_config.RUNS_DIR
    pm_config.INSTANCE_FILE, pm_config.RUNS_DIR = instance, runs
    try:
        yield pm_config
    finally:
        pm_config.INSTANCE_FILE, pm_config.RUNS_DIR = saved


class View:
    """pm-agent's SNClient interface over the orchestrator's client."""

    def __init__(self, sn: SNClient, purpose: str) -> None:
        self.sn, self.purpose = sn, purpose
        self.links: dict[str, list[str]] = {}       # planned problem sys_id -> incident sys_ids
        self.dry_run = sn.dry_run
        self.session = type("S", (), {"auth": (sn.identity, None)})()

    def get_all(self, table, query="", fields=None, page=500, display_value=False):
        m = PARENT.match(query or "")
        if table == "incident" and m and m.group(1) in self.links:
            ids = self.links[m.group(1)]
            query = f"sys_idIN{','.join(ids)}" if ids else "sys_id=none"
        out, offset = [], 0
        while True:
            rows = self.sn.list(table, query + "^ORDERBYsys_id" if query else "ORDERBYsys_id", fields,
                                purpose=self.purpose, limit=page, display=display_value, offset=offset)
            out += rows
            if len(rows) < page:
                return out
            offset += page

    def get(self, table, query="", fields=None, limit=100, offset=0, display_value=False):
        return self.sn.list(table, query, fields, purpose=self.purpose, limit=limit, display=display_value, offset=offset)

    def count(self, table, query=""):
        m = PARENT.match(query or "")
        if table == "incident" and m and m.group(1) in self.links:
            return len(self.links[m.group(1)])
        return self.sn.count(table, query, purpose=self.purpose)

    def create(self, table, data, params=None):
        _, row = self.sn.create(table, data, purpose=f"{self.purpose}: create {table}")
        return row

    def update(self, table, sys_id, data, params=None):
        _, row = self.sn.update(table, sys_id, data, purpose=f"{self.purpose}: update {table}")
        return row


def world(view: View, tag: str) -> tuple[list[dict], dict]:
    """pm-agent's (all_incidents, cis) for a run on Larkspur CIs (rca_agent.load_world reads tagged CIs)."""
    incidents = view.get_all("incident", f"correlation_id={tag}", fields=["number", "cmdb_ci", "category", "subcategory"])
    ids = sorted({i["cmdb_ci"] for i in incidents if i["cmdb_ci"]})
    cis = {}
    for k in range(0, len(ids), 50):
        for r in view.get_all("cmdb_ci", f"sys_idIN{','.join(ids[k:k + 50])}", fields=["sys_id", "name", "sys_class_name"]):
            cis[r["sys_id"]] = {"name": r["name"], "class": r["sys_class_name"], "attrs": {}}
    return incidents, cis
