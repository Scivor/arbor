"""
sources/http_util.py
Shared HTTP helpers for data sources — retry with exponential backoff.
"""

from __future__ import annotations

import time
from typing import Any, Optional


def retry_get(session, url: str, *, attempts: int = 3, **kwargs: Any):
    """
    GET with exponential backoff (1s, 2s, …).

    Raises the last exception if all attempts fail.
    Returns the successful Response, or None only if attempts < 1.
    """
    last_err: Optional[BaseException] = None
    for attempt in range(max(attempts, 0)):
        try:
            resp = session.get(url, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as e:
            last_err = e
            if attempt < attempts - 1:
                time.sleep(2**attempt)
            else:
                raise last_err
    return None
