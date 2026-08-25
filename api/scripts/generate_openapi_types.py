from __future__ import annotations

from pathlib import Path

from app.main import create_app

target = Path(__file__).parents[2] / "web" / "types" / "api.ts"
target.parent.mkdir(parents=True, exist_ok=True)
schema = create_app().openapi()
target.write_text(
    "// Generated from FastAPI OpenAPI. Do not hand-edit.\n"
    f"export const openapiVersion = {schema['openapi']!r} as const;\n"
    "export type HealthResponse = { status: string; db: string };\n",
    encoding="utf-8",
)
