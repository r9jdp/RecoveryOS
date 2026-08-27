"""Export the FastAPI schema for the generated TypeScript client."""

from __future__ import annotations

import json
from pathlib import Path

from services.api.app.main import app


def main() -> None:
    target = Path("packages/contracts/openapi.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
