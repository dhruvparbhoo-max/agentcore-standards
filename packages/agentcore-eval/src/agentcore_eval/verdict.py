"""Ship verdicts. CI green is not one of these."""

from enum import StrEnum
from pathlib import Path


class VerdictStatus(StrEnum):
    """Independent surface result. Auto-merge is allowed only for PASS and PASS+NOTES."""

    PASS = "PASS"
    PASS_NOTES = "PASS+NOTES"
    FAIL = "FAIL"


class Verdict:
    """One eval's result plus where its evidence was written."""

    def __init__(
        self,
        *,
        status: VerdictStatus,
        eval_name: str,
        agent_version: str,
        notes: tuple[str, ...],
        failures: tuple[str, ...],
        evidence_path: Path | None,
    ) -> None:
        self.status = status
        self.eval_name = eval_name
        self.agent_version = agent_version
        self.notes = notes
        self.failures = failures
        self.evidence_path = evidence_path


class Report:
    """Verdicts from one suite run."""

    def __init__(self, verdicts: tuple[Verdict, ...]) -> None:
        self.verdicts = verdicts

    @property
    def ok(self) -> bool:
        return all(item.status is not VerdictStatus.FAIL for item in self.verdicts)
