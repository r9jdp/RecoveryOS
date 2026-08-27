"""RecoveryOS health endpoints.

The application factory should include ``health_router`` without an API prefix so
that infrastructure can always reach ``/health/live`` and ``/health/ready``.
"""

from .router import router as health_router

__all__ = ["health_router"]
