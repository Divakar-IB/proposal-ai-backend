#!/usr/bin/env bash
# Container entrypoint for the Proposal AI backend.
#
# Commands:
#   serve            (default) run the API with uvicorn
#   migrate          run `alembic upgrade head` and exit
#   <anything else>  exec'd verbatim (e.g. `bash`, `pytest`, `alembic ...`)
#
# Env knobs:
#   PORT            listen port                 (default 8000)
#   HOST            bind address                (default 0.0.0.0)
#   WORKERS         uvicorn worker processes    (default 1 — see note below)
#   RELOAD          "1" to enable --reload      (dev only; needs source mounted)
#   RUN_MIGRATIONS  "1" to run alembic upgrade head before serving
#   LOG_LEVEL       uvicorn log level           (default info)
set -euo pipefail

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
WORKERS="${WORKERS:-1}"
LOG_LEVEL="${LOG_LEVEL:-info}"

# config.py hard-requires CONFIG (a JSON string). It's loaded either from a
# mounted .env via python-dotenv, or straight from the process environment.
# Fail loudly here rather than deep inside pydantic on import.
if [ -z "${CONFIG:-}" ] && [ ! -f /app/.env ]; then
  echo "ERROR: neither the CONFIG env var nor /app/.env is present." >&2
  echo "       Mount your .env (-v \"\$PWD/.env:/app/.env:ro\") or pass -e CONFIG='{...}'." >&2
  exit 1
fi

run_migrations() {
  echo "==> alembic upgrade head"
  alembic upgrade head
}

case "${1:-serve}" in
  serve)
    if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
      run_migrations
    fi

    if [ "${RELOAD:-0}" = "1" ]; then
      echo "==> uvicorn (reload) on ${HOST}:${PORT}"
      exec uvicorn main:app --host "$HOST" --port "$PORT" --reload --log-level "$LOG_LEVEL"
    fi

    # Default is a single worker on purpose:
    #  - proposal generation streams over SSE from an in-process generator
    #  - document/requirement processing runs on FastAPI BackgroundTasks,
    #    i.e. inside this same process (the Arq queue is inert)
    #  - each worker loads its own copy of the PPStructureV3 models (~1GB RSS)
    # Scale with replicas behind a load balancer rather than WORKERS>1 unless
    # you have measured the memory headroom.
    echo "==> uvicorn on ${HOST}:${PORT} (workers=${WORKERS})"
    exec uvicorn main:app --host "$HOST" --port "$PORT" --workers "$WORKERS" --log-level "$LOG_LEVEL"
    ;;
  migrate)
    run_migrations
    ;;
  *)
    exec "$@"
    ;;
esac
