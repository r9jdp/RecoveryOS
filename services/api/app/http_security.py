"""Credentialed browser-origin configuration shared by the API entrypoint."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def credentialed_web_origins(configured: str) -> list[str]:
    """Return exact HTTP(S) origins suitable for credentialed CORS.

    Credentialed CORS cannot safely use a wildcard. Paths, query strings, URL
    credentials, and fragments are rejected because browsers send only an
    origin in the ``Origin`` header.
    """

    origins: list[str] = []
    for raw_origin in configured.split(","):
        origin = raw_origin.strip().rstrip("/")
        if not origin:
            continue
        parsed = urlsplit(origin)
        if (
            "*" in origin
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError(
                "WEB_ORIGIN must contain only exact comma-separated HTTP(S) origins."
            )
        if origin not in origins:
            origins.append(origin)
    if not origins:
        raise RuntimeError("WEB_ORIGIN must contain at least one exact browser origin.")
    return origins


def install_credentialed_cors(app: FastAPI, configured_origins: str) -> None:
    """Install the API browser boundary with cookies and explicit CSRF headers."""

    app.add_middleware(
        CORSMiddleware,
        allow_origins=credentialed_web_origins(configured_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Content-Type",
            "X-RecoveryOS-CSRF-Token",
            "X-Voice-Event-Id",
        ],
    )
