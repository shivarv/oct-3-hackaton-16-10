# Housing

Full-stack housing listings app: **React (Vite + TypeScript)** frontend, **Python (FastAPI)** backend, **PostgreSQL** database.

```
.
├── frontend/          React 19 + Vite + TypeScript
├── backend/           FastAPI + SQLAlchemy 2 + Alembic
├── docs/              Setup and architecture docs
├── docker-compose.yml Postgres 16 for local development
└── .env.example       Shared environment config (copy to .env)
```

## Quick start

Prerequisites: Node 20+, Python 3.11+, Docker.

```bash
# 1. Config
cp .env.example .env

# 2. Database
docker compose up -d --wait

# 3. Backend  (terminal 1)
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 4. Frontend (terminal 2)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. API docs are at http://localhost:8000/docs.

| Service    | URL                         |
|------------|-----------------------------|
| Frontend   | http://localhost:5173       |
| Backend    | http://localhost:8000       |
| Swagger UI | http://localhost:8000/docs  |
| Postgres   | `localhost:5433` (user/pass/db: `housing`) |

> Postgres is mapped to **5433**, not 5432, so it doesn't collide with a locally installed Postgres.

## Docs

- [docs/SETUP.md](docs/SETUP.md): detailed setup, environment variables, troubleshooting
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): how the pieces fit together, and how to add a feature
- [backend/README.md](backend/README.md): backend commands, migrations, tests
- [frontend/README.md](frontend/README.md): frontend commands and API client

## Common commands

| Task | Command |
|------|---------|
| Start DB | `docker compose up -d --wait` |
| Stop DB | `docker compose down` (add `-v` to wipe data) |
| Run backend tests | `cd backend && pytest` |
| Lint backend | `cd backend && ruff check .` |
| New migration | `cd backend && alembic revision --autogenerate -m "msg"` |
| Apply migrations | `cd backend && alembic upgrade head` |
| Frontend build | `cd frontend && npm run build` |
| Frontend lint | `cd frontend && npm run lint` |
