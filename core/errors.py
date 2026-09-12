"""Safe error shaping: never leak credentials, paths, or driver internals."""

from __future__ import annotations

import re

_PATTERNS = [
    # scheme://user:password@...
    (re.compile(r"://([^:/@\s]+):[^@/\s]*@"), r"://\1:***@"),
    # quoted passwords
    (re.compile(r"(?i)(password\s*[=:]\s*)['\"]?[^\s'\",;]+['\"]?"), r"\1***"),
    # connection strings
    (re.compile(r"(?i)\b(postgresql|mysql|sqlite)(\+\w+)?://[^\s]+"), "[connection-string]"),
    # absolute filesystem paths
    (re.compile(r"(?:[A-Za-z]:\\|\/)[^\s\"']*"), "[path]"),
    # IPv4 addresses
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "[host]"),
]


def sanitize_error(exc_or_msg: object, max_len: int = 300) -> str:
    """Redact secrets/paths/hosts from an error message for client responses."""
    try:
        msg = str(exc_or_msg)
    except Exception:
        return "An error occurred."
    for pattern, repl in _PATTERNS:
        try:
            msg = pattern.sub(repl, msg)
        except Exception:
            continue
    msg = " ".join(msg.split())
    return msg[:max_len] if len(msg) > max_len else msg
