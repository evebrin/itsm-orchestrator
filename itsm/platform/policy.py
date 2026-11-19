"""The orchestrator's policy (END_TO_END_ITSM.md §5.1, §7.6).

`config/policy.yaml` holds the sections `incident`, `problem` and `autonomy`. The `change` section is the change
repository's own `config/policy.yaml`, read from the pinned submodule rather than copied, so the two cannot drift
before PR C1 lets that repository read ours.

Rules enforced on load, not left to the file: High is never auto-approved (D6); caps and limits are positive
whole numbers; every threshold the design names is present.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "config" / "policy.yaml"
CHANGE_POLICY = ROOT / "vendor" / "ChangeManagementAgent" / "config" / "policy.yaml"
TIERS = ("low", "moderate", "high")
CONFIDENCE = ("Low", "Medium", "High")


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class Policy:
    incident: dict
    problem: dict
    autonomy: dict
    change: dict
    root: Path

    def kill_switch(self) -> bool:
        """True while the kill-switch file exists: no approvals; incidents continue."""
        return (self.root / self.autonomy["kill_switch_file"]).exists()

    def auto_approves(self, tier: str) -> bool:
        return self.autonomy["enabled"] and tier in self.autonomy["auto_approve_normal_tiers"]


def _need(section: dict, name: str, key: str, kind):
    if key not in section:
        raise PolicyError(f"policy {name}.{key} is missing")
    if not isinstance(section[key], kind) or isinstance(section[key], bool) and kind is not bool:
        raise PolicyError(f"policy {name}.{key} has the wrong type")
    return section[key]


def _positive(section: dict, name: str, key: str) -> None:
    v = _need(section, name, key, int)
    if v < 1:
        raise PolicyError(f"policy {name}.{key} must be at least 1")


def load(path: Path = POLICY, change_path: Path = CHANGE_POLICY, root: Path = ROOT) -> Policy:
    try:
        doc = yaml.safe_load(Path(path).read_text()) or {}
        change = yaml.safe_load(Path(change_path).read_text()) or {}
    except (OSError, yaml.YAMLError) as e:
        raise PolicyError(f"cannot read the policy: {type(e).__name__}") from None
    for name in ("incident", "problem", "autonomy"):
        if not isinstance(doc.get(name), dict):
            raise PolicyError(f"policy section {name!r} is missing")
    inc, prb, aut = doc["incident"], doc["problem"], doc["autonomy"]

    c = _need(inc, "incident", "min_confidence", float)
    if not 0 <= c <= 1:
        raise PolicyError("policy incident.min_confidence must be between 0 and 1")
    if _need(prb, "problem", "min_confidence", str) not in CONFIDENCE:
        raise PolicyError(f"policy problem.min_confidence must be one of {CONFIDENCE}")

    _need(aut, "autonomy", "enabled", bool)
    tiers = _need(aut, "autonomy", "auto_approve_normal_tiers", list)
    if any(t not in TIERS for t in tiers):
        raise PolicyError(f"policy autonomy.auto_approve_normal_tiers may only name {TIERS}")
    if "high" in tiers:
        raise PolicyError("policy may not auto-approve High changes (D6: above delegated authority)")
    caps = _need(aut, "autonomy", "caps", dict)
    for k in ("per_service_per_day", "per_run"):
        _positive(caps, "autonomy.caps", k)
    _positive(aut, "autonomy", "max_impacted_services")
    cb = _need(aut, "autonomy", "circuit_breaker", dict)
    for k in ("failed_changes", "window_days"):
        _positive(cb, "autonomy.circuit_breaker", k)
    if _need(cb, "autonomy.circuit_breaker", "scope", str) != "service":
        raise PolicyError("policy autonomy.circuit_breaker.scope must be 'service'")
    ks = _need(aut, "autonomy", "kill_switch_file", str)
    if Path(ks).is_absolute() or ".." in Path(ks).parts:
        raise PolicyError("policy autonomy.kill_switch_file must be a path inside the project")

    for k in ("timezone", "freezes", "lead_time_business_days", "change_authority"):
        if k not in change:
            raise PolicyError(f"change repository policy is missing {k!r}")
    return Policy(inc, prb, aut, change, Path(root))
