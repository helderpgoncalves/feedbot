# feedbot-api

FastAPI service that owns the Feedbot data model and serves both the REST API (`/v1/*`) and the web dashboard (`/`, `/app/*`).

## Endpoints

### Public

| Route | Purpose |
|---|---|
| `GET /` | Marketing landing |
| `GET /login`, `POST /login` | Magic-link auth |
| `GET /login/verify` | Consume token, set session |
| `POST /logout` | Clear session |
| `GET /healthz` | Liveness |

### Dashboard (session-authenticated)

| Route | Purpose |
|---|---|
| `GET /app` | List projects |
| `POST /app/projects` | Create project |
| `GET /app/projects/{slug}` | Inbox + keys + stats |
| `POST /app/projects/{slug}/keys` | Issue an API key |

### v1 API (Bearer-authenticated)

| Method | Route | Purpose |
|---|---|---|
| GET | `/v1/feedbacks` | List with filters |
| POST | `/v1/feedbacks` | Create (bot or web ingestion) |
| GET | `/v1/feedbacks/{id}` | Detail |
| PATCH | `/v1/feedbacks/{id}` | Update status / note / reply_to_user |
| GET | `/v1/stats` | Counts per status |

## Run

```bash
docker compose up db -d
alembic upgrade head
uvicorn feedbot_api.app:app --reload
```
