#!/usr/bin/env python3
"""
McNeillium_AI — Agent 47: Error Recovery Specialist

A small retry wrapper used by every other agent. Handles the most common
runtime failures with sensible exponential backoff:

  - HTTP 429 / "rate limit" / "Too Many Requests"     → sleep + retry
  - HTTP 503 / "Service Unavailable"                  → sleep + retry
  - urllib.error.URLError / ConnectionError           → sleep + retry
  - subprocess CalledProcessError                     → one retry
  - FileNotFoundError                                 → fail fast (no retry)
  - OSError [Errno 28]: disk full                     → cleanup + retry
  - default                                           → one retry then give up

Each retry doubles the wait (capped at 60s). Total attempts default to 3.

Public API:
  retry(func, *args, **kwargs)  — call func with retries
  @recover                       — decorator form
  log_alert(message)             — append to logs/alerts.md
"""

import datetime
import functools
import io
import shutil
import subprocess
import sys
import time
import urllib.error
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower().replace("-", "") != "utf8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALERTS = PROJECT_ROOT / "logs" / "alerts.md"
TEMP_DIRS = [
    PROJECT_ROOT / "output" / "_temp_v4",
    PROJECT_ROOT / "output" / "_clip_cache",
]

DEFAULT_RETRIES = 3
BASE_BACKOFF_S = 4
MAX_BACKOFF_S = 60


def log_alert(message, severity="warning"):
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"- [{stamp}] **{severity.upper()}** — {message}"
    with open(ALERTS, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _classify(exc):
    """Return (should_retry, hint)."""
    if isinstance(exc, FileNotFoundError):
        return False, "missing file — fail fast"
    if isinstance(exc, OSError) and getattr(exc, "errno", None) == 28:
        return True, "disk full — cleanup before retry"
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (429, 503):
            return True, f"HTTP {exc.code} — backoff"
        if 500 <= exc.code < 600:
            return True, f"HTTP {exc.code} — server-side, retry"
        return False, f"HTTP {exc.code} — client error"
    if isinstance(exc, (urllib.error.URLError, ConnectionError, TimeoutError)):
        return True, "network blip — retry"
    if isinstance(exc, subprocess.CalledProcessError):
        return True, "subprocess failure — one retry"
    txt = str(exc).lower()
    if "rate limit" in txt or "too many requests" in txt:
        return True, "rate-limited — backoff"
    return True, "unknown — single retry"


def _cleanup_temp():
    freed = 0
    for d in TEMP_DIRS:
        if d.exists():
            try:
                size = sum(p.stat().st_size for p in d.rglob("*") if p.is_file())
                shutil.rmtree(d, ignore_errors=True)
                freed += size
            except Exception:
                pass
    return freed


def retry(func, *args, max_attempts=DEFAULT_RETRIES,
          backoff=BASE_BACKOFF_S, on_failure=None, **kwargs):
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exc = e
            should, hint = _classify(e)
            print(f"  ⚠️  attempt {attempt}/{max_attempts}: {type(e).__name__} "
                  f"— {hint}")
            if not should or attempt == max_attempts:
                break
            if "disk full" in hint:
                freed = _cleanup_temp()
                print(f"      🧹 freed {freed / 1e6:.1f}MB of temp files")
            wait = min(MAX_BACKOFF_S, backoff * (2 ** (attempt - 1)))
            print(f"      ⏳ sleeping {wait}s before retry")
            time.sleep(wait)
    log_alert(
        f"{func.__name__} failed after {max_attempts} attempts: "
        f"{type(last_exc).__name__}: {last_exc}",
        severity="error",
    )
    if on_failure is not None:
        return on_failure
    raise last_exc


def recover(max_attempts=DEFAULT_RETRIES, on_failure=None):
    """Decorator form. Wraps any function with retry()."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            return retry(fn, *args,
                         max_attempts=max_attempts,
                         on_failure=on_failure, **kwargs)
        return wrapped
    return deco


# Quick self-test
if __name__ == "__main__":
    @recover(max_attempts=2, on_failure="fallback")
    def flaky():
        raise urllib.error.URLError("simulated network drop")

    print("Self-test:", flaky())
