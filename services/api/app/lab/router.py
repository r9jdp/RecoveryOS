"""Coordinator-registerable RecoveryBench report routes."""

from fastapi import APIRouter, FastAPI, HTTPException, status

from .report_store import RecoveryBenchReportStore, ReportNotFoundError
from .schemas import LabReport

router = APIRouter(prefix="/v1/lab", tags=["lab"])


def get_report_store() -> RecoveryBenchReportStore:
    return RecoveryBenchReportStore()


@router.get("/reports/latest", response_model=LabReport)
def get_latest_report() -> LabReport:
    try:
        return get_report_store().latest()
    except ReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No RecoveryBench report is available.",
        ) from exc


@router.get("/reports/{version}", response_model=LabReport)
def get_versioned_report(version: str) -> LabReport:
    try:
        return get_report_store().load(version)
    except ReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"RecoveryBench report {version!r} was not found.",
        ) from exc


def install_lab_api(app: FastAPI) -> None:
    app.include_router(router)
