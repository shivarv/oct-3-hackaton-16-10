# Architecture

```
Browser ──► Vite dev server :5173 ──/api/*──► FastAPI :8000 ──► Postgres :5433
             (React SPA)            proxy       (SQLAlchemy)      (Docker)
```

- **Frontend** is a single-page React app. All HTTP calls go through `frontend/src/api.ts`.
- **Backend** is a FastAPI app. Every route lives under `/api`. DB sessions are injected per request through the `DbSession` dependency.
- **Database** schema is owned by Alembic migrations in `backend/alembic/versions/`. Never edit tables by hand.

## Backend layout

```
backend/
├── app/
│   ├── main.py          FastAPI app, CORS, router registration, /api/health
│   ├── config.py        Settings loaded from the root .env (pydantic-settings)
│   ├── db.py            Engine, SessionLocal, Base, get_db, DbSession
│   ├── models.py        SQLAlchemy ORM models (tables)
│   ├── schemas.py       Pydantic request/response models
│   └── routers/
│       └── listings.py  /api/listings CRUD
├── alembic/             Migrations (env.py reads DATABASE_URL from app.config)
└── tests/               pytest (runs against the dev DB)
```

## API

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/api/health` | | `{status, db}` |
| GET | `/api/listings?city=` | | `Listing[]` |
| GET | `/api/listings/{id}` | | `Listing` / 404 |
| POST | `/api/listings` | `ListingCreate` | `Listing` (201) |
| DELETE | `/api/listings/{id}` | | 204 / 404 |

The full interactive spec is at http://localhost:8000/docs.

## Data model

`listings`

| Column | Type | Notes |
|--------|------|-------|
| id | integer PK | |
| title | varchar(200) | |
| description | text | nullable |
| address | varchar(300) | |
| city | varchar(100) | indexed |
| price | numeric(12,2) | serialized as a string in JSON |
| bedrooms | integer | default 1 |
| bathrooms | integer | default 1 |
| created_at | timestamptz | server default `now()` |

## Adding a new resource (checklist)

1. **Model:** add a class to `app/models.py`.
2. **Migration:** `alembic revision --autogenerate -m "add <thing>"`. Review the generated file, then run `alembic upgrade head`.
3. **Schemas:** add `<Thing>Create` / `<Thing>Read` to `app/schemas.py`.
4. **Router:** create `app/routers/<things>.py` with `prefix="/api/<things>"` and register it in `app/main.py`.
5. **Tests:** add `tests/test_<things>.py`.
6. **Frontend:** add types and functions to `src/api.ts`, then use them in components.
