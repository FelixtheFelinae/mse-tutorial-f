from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List


class Action(str, Enum):
    AUTO_PUBLISH = "AUTO_PUBLISH"
    AUTO_PUBLISH_WITH_LIGHT_EDIT = "AUTO_PUBLISH_WITH_LIGHT_EDIT"
    RETURN_FOR_REVISION = "RETURN_FOR_REVISION"
    QUARANTINE = "QUARANTINE"


ACTION_PRIORITY = {
    Action.AUTO_PUBLISH: 0,
    Action.AUTO_PUBLISH_WITH_LIGHT_EDIT: 1,
    Action.RETURN_FOR_REVISION: 2,
    Action.QUARANTINE: 3,
}


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    message: str
    line: int = 0
    evidence: str = ""

    def __post_init__(self) -> None:
        if self.severity not in {"note", "review", "blocking"}:
            raise ValueError("severity must be note, review, or blocking")


@dataclass
class CheckReport:
    path: str
    findings: List[Finding] = field(default_factory=list)
    checks_run: List[str] = field(default_factory=list)

    @property
    def action(self) -> Action:
        if any(item.severity == "blocking" for item in self.findings):
            return Action.QUARANTINE
        if any(item.severity == "review" for item in self.findings):
            return Action.RETURN_FOR_REVISION
        if self.findings:
            return Action.AUTO_PUBLISH_WITH_LIGHT_EDIT
        return Action.AUTO_PUBLISH

    def to_dict(self) -> Dict[str, object]:
        return {
            "path": self.path,
            "action": self.action.value,
            "checks_run": list(self.checks_run),
            "findings": [asdict(item) for item in self.findings],
        }


def strictest_action(actions: List[Action]) -> Action:
    if not actions:
        return Action.AUTO_PUBLISH
    return max(actions, key=lambda item: ACTION_PRIORITY[item])
