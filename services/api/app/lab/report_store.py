"""Read-only versioned report store; it never accesses merchant persistence."""

from __future__ import annotations

from pathlib import Path

from .schemas import LabReport

DEFAULT_REPORT_ROOT = Path(__file__).resolve().parents[4] / "ml" / "recoverybench" / "artifacts"


class ReportNotFoundError(FileNotFoundError):
    pass


class RecoveryBenchReportStore:
    def __init__(self, root: Path = DEFAULT_REPORT_ROOT) -> None:
        self.root = root

    def load(self, version: str) -> LabReport:
        if not version or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for character in version
        ):
            raise ReportNotFoundError(version)
        report_path = self.root / version / "report.json"
        if not report_path.is_file():
            raise ReportNotFoundError(version)
        return LabReport.model_validate_json(report_path.read_text(encoding="utf-8"))

    def latest(self) -> LabReport:
        versions = sorted(path.name for path in self.root.glob("recoverybench.v*") if path.is_dir())
        if not versions:
            raise ReportNotFoundError("latest")
        return self.load(versions[-1])
