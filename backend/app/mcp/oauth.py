"""OAuth 2.0 authorization code storage for the MCP server.

Uses a simple in-memory store with TTL — no Redis dependency.
Auth codes are short-lived (10 min) and single-instance is fine for this use case.
"""

import base64
import hashlib
import secrets
import threading
import time

CODE_TTL = 600  # 10 minutes

# { "mcp_code:{code}": (data_dict, expire_at_unix) }
_store: dict[str, tuple[dict, float]] = {}
_lock = threading.Lock()


def generate_code() -> str:
    return secrets.token_urlsafe(32)


def store_auth_code(
    code: str,
    user_id: str,
    redirect_uri: str,
    code_challenge: str | None = None,
    code_challenge_method: str | None = None,
) -> None:
    data = {
        "user_id": user_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
    }
    expire_at = time.monotonic() + CODE_TTL
    key = f"mcp_code:{code}"
    with _lock:
        _store[key] = (data, expire_at)
        # Opportunistic cleanup of expired entries
        now = time.monotonic()
        expired = [k for k, (_, exp) in _store.items() if exp < now]
        for k in expired:
            del _store[k]


def consume_auth_code(code: str) -> dict | None:
    key = f"mcp_code:{code}"
    with _lock:
        entry = _store.pop(key, None)
    if entry is None:
        return None
    data, expire_at = entry
    if time.monotonic() > expire_at:
        return None
    return data


def verify_pkce(code_verifier: str, code_challenge: str, method: str) -> bool:
    if method == "S256":
        digest = hashlib.sha256(code_verifier.encode()).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return expected == code_challenge
    if method == "plain":
        return code_verifier == code_challenge
    return False
