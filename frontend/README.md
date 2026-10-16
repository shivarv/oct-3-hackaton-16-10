# Frontend (React + Vite + TypeScript)

## Setup and run

```bash
npm install
npm run dev        # http://localhost:5173
```

The backend must be running. In dev, Vite proxies `/api/*` to `http://localhost:8000`. To point it elsewhere, create `.env.local`:

```
VITE_PROXY_TARGET=http://localhost:8001
```

## Scripts

| Command | What it does |
|---------|--------------|
| `npm run dev` | Dev server with hot reload |
| `npm run build` | Type-check (`tsc -b`) and production build into `dist/` |
| `npm run preview` | Serve the built `dist/` locally |
| `npm run lint` | oxlint |

## Structure

```
src/
├── api.ts     Typed API client. All backend calls go through here.
├── App.tsx    Listings page (list, create, delete)
├── main.tsx   React entry point
└── *.css
```

## Production

Set `VITE_API_URL` to the deployed backend URL at build time:

```bash
VITE_API_URL=https://api.example.com npm run build
```

Also add the frontend's origin to the backend's `CORS_ORIGINS`.
