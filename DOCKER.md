# Running Proposal AI Backend in Docker

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | Two-stage build (builder venv → slim runtime with native libs) |
| `.dockerignore` | Keeps `.env`, `.venv/`, `.git/`, caches out of the build context |
| `docker/entrypoint.sh` | Startup script — `serve` / `migrate` / arbitrary command |
| `docker-compose.yml` | `api` service (+ optional `db` and `redis` profiles) |
| `docker-compose.dev.yml` | Dev override: bind-mounted source + `--reload` |

## Prerequisites

- Docker Desktop (Windows/macOS) or Docker Engine 24+ with the Compose v2 plugin.
- A valid `.env` in the project root containing the `CONFIG` JSON blob (the same one
  you already use for `uvicorn main:app --reload`).

## Configuration

`config.py` requires a **single `CONFIG` environment variable** holding the whole config
as JSON. Two supported ways to supply it:

**1. Mount `.env` (default, used by compose).** `config.py` calls `load_dotenv()`, and
python-dotenv handles the multi-line quoted JSON correctly:

```bash
-v "$PWD/.env:/app/.env:ro"
```

**2. Pass `CONFIG` directly (recommended for production/CI).** This must be a
*single-line* JSON string — most orchestrators (ECS, Render, Kubernetes secrets) take it
that way:

```bash
-e CONFIG='{"database":{...},"jwt":{...},"aws":{...}, ...}'
```

The entrypoint fails fast with a clear message if neither is present.

> `.env` is deliberately listed in `.dockerignore` — secrets are never baked into an
> image layer. Your current `.env` holds live DB/AWS/Groq/Pinecone/SMTP credentials, so
> keep it mounted rather than copied, and don't push an image built with it.

## Build

```bash
# from the project root
docker build -t proposal-ai-backend:latest .
```

First build pulls PaddlePaddle + PaddleX and takes roughly 10–20 minutes; the final image
is large (~4–6 GB) because of the OCR stack. Rebuilds after a code change are fast — only
the last `COPY . .` layer is invalidated. Rebuilds after a `requirements.txt` change reuse
the BuildKit pip cache.

## Run

### With Docker Compose (easiest)

```bash
docker compose up --build              # start
docker compose logs -f api             # follow logs
docker compose down                    # stop
```

API is then on <http://localhost:8000> — Swagger UI at <http://localhost:8000/docs>.

Development mode with hot reload:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Run against a **local** Postgres instead of the remote one:

```bash
docker compose --profile localdb up --build
```

…and set `CONFIG.database` to `host: "db"`, `port: 5432`, with the `POSTGRES_USER` /
`POSTGRES_PASSWORD` / `POSTGRES_DB` values from `docker-compose.yml`.

To reach a Postgres running directly on your Windows host, set
`CONFIG.database.host` to `host.docker.internal`.

### With plain `docker run`

```bash
docker run --rm -p 8000:8000 \
  -v "$PWD/.env:/app/.env:ro" \
  -v proposal-ai-paddlex:/home/app/.paddlex \
  --name proposal-ai-api \
  proposal-ai-backend:latest
```

PowerShell equivalent:

```powershell
docker run --rm -p 8000:8000 `
  -v "${PWD}\.env:/app/.env:ro" `
  -v proposal-ai-paddlex:/home/app/.paddlex `
  --name proposal-ai-api `
  proposal-ai-backend:latest
```

## Runtime knobs

Set as environment variables (`-e` or the compose `environment:` block):

| Var | Default | Meaning |
|---|---|---|
| `PORT` | `8000` | Listen port |
| `HOST` | `0.0.0.0` | Bind address |
| `WORKERS` | `1` | Uvicorn worker processes |
| `RELOAD` | `0` | `1` = `--reload` (dev only, needs source mounted) |
| `RUN_MIGRATIONS` | `0` | `1` = `alembic upgrade head` before serving |
| `LOG_LEVEL` | `info` | Uvicorn log level |

**Keep `WORKERS=1` unless you've measured memory.** Proposal generation streams SSE from
an in-process generator, document/requirement processing runs on FastAPI
`BackgroundTasks` in the same process, and every worker loads its own ~1 GB copy of the
PPStructureV3 models. Scale with container replicas behind a load balancer instead.

## Migrations and one-off commands

```bash
docker compose run --rm api migrate                              # alembic upgrade head
docker compose run --rm api alembic revision --autogenerate -m "msg"
docker compose run --rm api bash                                 # shell inside the image
docker compose run --rm api pytest                               # run the test suite
```

`main.py`'s lifespan already runs `Base.metadata.create_all`, which is why migrations are
opt-in rather than automatic on boot.

## Notes on the native dependencies

The runtime stage installs these because pip alone isn't enough:

- **`pandoc`** — `pypandoc` is only a wrapper around the binary (`rendering/renderer.py`,
  `rendering/html_renderer.py`).
- **Pango / Cairo / GDK-PixBuf / libffi / fonts** — WeasyPrint's PDF backend.
  `fonts-dejavu-core` + `fonts-liberation` are included so exported PDFs don't fall back
  to tofu boxes.
- **`libgl1`, `libglib2.0-0`, `libsm6`, `libxext6`, `libxrender1`** — `opencv-contrib-python`,
  which `paddlex[ocr]` hard-requires by exact package name.
- **`libgomp1`** — PaddlePaddle's OpenMP runtime.

The PaddleX model cache lives at `/home/app/.paddlex` (`PADDLE_PDX_CACHE_HOME`) and is a
named volume, so the ~1 GB first-OCR download happens once rather than on every restart.

## Troubleshooting

- **`CONFIG environment variable is required`** — `.env` wasn't mounted, or you built an
  image expecting it to be baked in. Use one of the two options above.
- **`exec /usr/local/bin/entrypoint.sh: no such file or directory`** — CRLF line endings.
  The Dockerfile strips them with `sed`, but if you edited the file and use a
  `core.autocrlf` checkout, confirm it's LF.
- **DB connection refused / times out** — the container's `localhost` is not your host's.
  Use `host.docker.internal` (host DB), `db` (the `localdb` profile), or the real remote
  host.
- **Healthcheck flapping on first boot** — `start_period` is 60s; the first OCR request
  additionally downloads models and can take a few minutes.
- **First build is slow / times out** — that's PaddlePaddle. Let it run once; the layer
  cache makes subsequent builds quick.
