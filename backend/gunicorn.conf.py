"""gunicorn settings for production (docker-compose.prod.yml).

gunicorn is the process manager around the uvicorn workers: it restarts a
worker that crashes (OOM kill, segfault in a driver) and kills + replaces a
worker whose event loop stops answering its heartbeat for `timeout` seconds,
all without restarting the container. Every value can be overridden through
the environment.
"""
import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


bind = "0.0.0.0:8000"
workers = _int("WEB_CONCURRENCY", 4)
worker_class = "uvicorn_worker.UvicornWorker"

# Seconds a worker's event loop may go without checking in before gunicorn
# replaces it. Long requests are fine (they await); only a blocked loop trips it.
timeout = _int("GUNICORN_TIMEOUT", 120)
# On restart/deploy: time for in-flight requests and order fixes to finish.
# Docker's stop_grace_period (120s) must stay above this.
graceful_timeout = _int("GUNICORN_GRACEFUL_TIMEOUT", 110)
# Above nginx's upstream keepalive_timeout (60s) so nginx never reuses a
# connection the backend is closing.
keepalive = _int("GUNICORN_KEEPALIVE", 75)

# Recycling workers after N requests caps slow memory growth, but each recycle
# also cuts the long reports / order fixes running on that worker, so it is
# off unless memory growth is actually observed (then try 20000 / 2000).
max_requests = _int("GUNICORN_MAX_REQUESTS", 0)
max_requests_jitter = _int("GUNICORN_MAX_REQUESTS_JITTER", 0)

# Access lines come from nginx (with timings); the app logs slow and failed
# requests itself (RequestLogMiddleware).
accesslog = None
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")
