# Operations

## Docker services

Project name: `vera` (`docker-compose.yml`)

| Container | Image | Port |
|-----------|-------|------|
| `vera-api` | `vera-api` | 8080 |
| `vera-web` | `vera-web` | 5173 → nginx:80 |

```powershell
cd C:\Parag-Personal\Kite
docker compose up -d --build
docker compose ps
docker compose logs -f api
```

Health: `GET http://localhost:8080/api/health`

---

## Data persistence

Named volume `vera_data` mounts to `/app/data` in the API container (SQLite + Chroma + uploads).

Wipe all VERA data (destructive):

```powershell
docker compose down
docker volume rm vera_vera_data
docker compose up -d --build
```

---

## CORS changes

Edit `VERA_CORS_ORIGINS` in `.env` **and** keep `docker-compose.yml` `environment` in sync if Compose overrides env_file.

```powershell
docker compose up -d api
```

---

## Name conflicts / orphan containers

```powershell
docker compose down --remove-orphans
docker rm -f vera-api vera-web
docker compose up -d --build
```

---

## Recreate API after code changes

```powershell
docker compose up -d --build api
```

Frontend image rebuild:

```powershell
docker compose up -d --build web
```

---

## Common failures

| Symptom | Action |
|---------|--------|
| UI loads, Ask fails | Check Azure keys; API logs; `/api/health` |
| CORS blocked from chatbot | Add `http://localhost:5500` to CORS; recreate API |
| Graph empty after ingest | Wait for weave job; check API logs for weaver errors |
| Publish 404 | Wrong agent id; list `/api/agents` |
| Port already allocated | Stop conflicting containers / processes |

---

## Companion chatbot

PlayReady static client: `C:\Parag-Personal\Vera_PlayReady_Chatbot`  
Docs there cover Docker on `:5500` and public API smoke tests.
