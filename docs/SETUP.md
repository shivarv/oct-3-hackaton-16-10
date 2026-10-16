# Setup Guide

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Node.js | 20+ | `node -v` |
| Python | 3.11+ | `python3 --version` |
| Docker + Compose | any recent | `docker compose version` |

On macOS with Colima instead of Docker Desktop, run `colima start` first.

## 1. Environment

```bash
cp .env.example .env
```

### Root `.env` (used by docker-compose and the backend)

| Variable | Default | Purpose |
|----------|---------|---------|
| `POSTGRES_USER` | `housing` | DB user created by the container |
| `POSTGRES_PASSWORD` | `housing` | DB password |
| `POSTGRES_DB` | `housing` | DB name |
| `POSTGRES_PORT` | `5433` | Host port mapped to the container's 5432 |
| `DATABASE_URL` | `postgresql+psycopg://housing:housing@localhost:5433/housing` | SQLAlchemy connection string |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins |

If you change user, password, db, or port, update `DATABASE_URL` to match.

### `frontend/.env.local` (optional)

| Variable | Purpose |
|----------|---------|
| `VITE_PROXY_TARGET` | Dev only. Where Vite forwards `/api/*`. Defaults to `http://localhost:8000`. |
| `VITE_API_URL` | Production builds. The absolute backend URL. Leave unset in dev. |

## 2. Database

```bash
docker compose up -d --wait   # starts Postgres 16, waits until healthy
docker compose ps             # should show housing-db (healthy)
```

Connect with psql:

```bash
docker exec -it housing-db psql -U housing -d housing
# or from the host:
psql postgresql://housing:housing@localhost:5433/housing
```

Reset all data: `docker compose down -v && docker compose up -d --wait`, then rerun migrations.

## 3. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head               # creates tables
uvicorn app.main:app --reload --port 8000
```

Verify: `curl localhost:8000/api/health` should return `{"status":"ok","db":"ok"}`.

## 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. In dev, requests to `/api/*` are proxied to the backend, so there are no CORS problems.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| `password authentication failed for user "housing"` | You're hitting a *different* Postgres (for example a native install on 5432). Check that `DATABASE_URL` uses port **5433**. |
| `address already in use` on 8000 | Something else holds port 8000 (`lsof -nP -iTCP:8000`). Run the backend on another port (`--port 8001`) and set `VITE_PROXY_TARGET=http://localhost:8001` in `frontend/.env.local`. |
| `failed to connect to the docker API` | Docker isn't running. Start Docker Desktop, or run `colima start`. |
| Port 5433 in use | Set `POSTGRES_PORT` to a free port in `.env` and update `DATABASE_URL`. |
| Frontend shows `Error: 500` / `502` | Backend isn't running, or the DB is down. Check `/api/health`. |
| `relation "listings" does not exist` | Run `alembic upgrade head`. |
