"""RecoveryBench report API and optional scorer factory."""

from .router import install_lab_api, router
from .scorer import create_recovery_scorer

__all__ = ["create_recovery_scorer", "install_lab_api", "router"]
