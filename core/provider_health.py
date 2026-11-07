"""Bounded retries for transient hosted-provider connectivity checks."""

import time


_TRANSIENT_CONNECTION_ERRORS = (
    "apiconnectionerror",
    "connecterror",
    "connecttimeout",
    "readtimeout",
    "apitimeouterror",
    "timeoutexception",
    "connection error",
    "connection reset",
    "timed out",
    "network is unreachable",
    "temporarily unavailable",
)


def ping_with_retry(provider, timeout: int, attempts: int = 3) -> bool:
    """Retry only transient transport errors; surface auth/config errors once."""
    for attempt in range(max(1, attempts)):
        try:
            return provider.ping(timeout=timeout)
        except Exception as exc:
            message = f"{type(exc).__name__} {exc}".lower()
            transient = any(marker in message for marker in _TRANSIENT_CONNECTION_ERRORS)
            if not transient or attempt + 1 >= max(1, attempts):
                raise
            time.sleep(min(0.4 * (2 ** attempt), 1.5))
    return False
