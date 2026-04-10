# ─────────────────────────────────────────────────────────────────────────────
#  Revenue AI — Gunicorn Configuration
#  Docs: https://docs.gunicorn.org/en/stable/settings.html
# ─────────────────────────────────────────────────────────────────────────────
import multiprocessing

# ── Binding ───────────────────────────────────────────────────────────────────
bind = "0.0.0.0:8000"

# ── Workers ───────────────────────────────────────────────────────────────────
# Formula: (2 × CPU cores) + 1  — safe default for I/O-bound Django apps
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"          # sync is correct; use "gthread" for thread safety
threads = 2                    # threads per worker

# ── Timeouts ──────────────────────────────────────────────────────────────────
# SSE streaming responses can take up to 5 minutes; set worker kills beyond that
timeout = 120          # worker silent timeout (seconds)
graceful_timeout = 30  # time to finish pending requests on SIGTERM
keepalive = 5          # keep-alive connections (seconds)

# ── Logging ───────────────────────────────────────────────────────────────────
accesslog  = "-"       # stdout (captured by Docker / systemd)
errorlog   = "-"       # stderr
loglevel   = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sµs'

# ── Process naming ────────────────────────────────────────────────────────────
proc_name = "revenueai"

# ── Reliability ───────────────────────────────────────────────────────────────
max_requests         = 1000   # restart worker after N requests (prevents memory leaks)
max_requests_jitter  = 100    # randomise restart to avoid all workers restarting at once
preload_app          = False  # set True only after verifying app is fork-safe

# ── Security ──────────────────────────────────────────────────────────────────
limit_request_line        = 4094
limit_request_fields      = 100
limit_request_field_size  = 8190
forwarded_allow_ips        = "*"  # trust X-Forwarded-For from Nginx (restrict to Nginx IP in production)
