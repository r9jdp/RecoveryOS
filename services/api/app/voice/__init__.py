"""Isolated voice API module; coordinator mounts `router` under the main API."""

from .router import router

__all__ = ["router"]
