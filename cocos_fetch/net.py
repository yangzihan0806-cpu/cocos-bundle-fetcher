"""Minimal HTTP download helpers with timeout, retry and resume."""

import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Tuple

USER_AGENT = "Mozilla/5.0"


def http_get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def file_ok(path: Path) -> bool:
    """A file counts as downloaded if it exists and is non-empty."""
    return path.is_file() and path.stat().st_size > 0


def download_if_needed(
    url: str,
    save_path: Path,
    timeout: float,
    retries: int,
    skip_existing: bool = True,
    backoff_cap: float = 3.0,
) -> Tuple[str, int, str]:
    """Download ``url`` to ``save_path``.

    Returns ``(status, size, error)`` where status is one of
    ``OK`` (downloaded), ``SKIP`` (already present) or ``MISS`` (all retries failed).
    Skipping non-empty existing files makes reruns idempotent, so an
    interrupted run can simply be restarted.
    """
    if skip_existing and file_ok(save_path):
        return "SKIP", save_path.stat().st_size, ""

    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            data = http_get(url, timeout=timeout)
            if not data:
                raise ValueError("empty response")
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(data)
            return "OK", len(data), ""
        except urllib.error.HTTPError as e:
            last_err = repr(e)
            if e.code in (403, 404, 410):  # definitive: the file isn't there, don't retry
                break
            if attempt < retries:
                time.sleep(min(attempt, backoff_cap))
        except Exception as e:  # timeouts, connection resets, empty bodies
            last_err = repr(e)
            if attempt < retries:
                time.sleep(min(attempt, backoff_cap))  # linear backoff, capped
    return "MISS", 0, last_err
