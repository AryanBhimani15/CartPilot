# CartPilot AI

Agentic commerce for a synthetic Indian D2C sportswear merchant. The application is built in
phases; its current foundation includes a FastAPI health endpoint, typed PostgreSQL schema and
deterministic catalog seed.

## Local development

1. Install PostgreSQL 14+, Node 20+ and [uv](https://docs.astral.sh/uv/).
2. Run `make setup` (it creates a local `.env` from the fake-value template if needed).
3. Adjust `DATABASE_URL` in `.env` if your local PostgreSQL user is not `postgres`.
4. Run `make seed` to create the database, migrate it and load the catalog.
5. Run `make dev`, then open `http://localhost:3000/shop` or `http://localhost:3000/dashboard`.

The API health check is `http://localhost:8000/api/v1/health`.

Never put live credentials in `.env.example`; it intentionally contains fake values.
