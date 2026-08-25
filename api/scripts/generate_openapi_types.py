"""Write the API's OpenAPI schema to disk for the frontend type generator.

This script only emits the schema. `make types` then runs `openapi-typescript`
over it, so `web/types/api.ts` is genuinely derived from the API surface rather
than hand-maintained (ARCHITECTURE.md §12, D-001).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import create_app

SCHEMA_PATH = Path(__file__).parents[2] / "web" / "types" / "openapi.json"


def main() -> None:
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = create_app().openapi()
    SCHEMA_PATH.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
