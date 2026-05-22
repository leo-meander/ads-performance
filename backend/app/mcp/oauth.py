import base64
import hashlib
import json
import secrets
from datetime import datetime, timezone

import redis as redis_lib

from app.config import settings

_redis_client = None


def _redis() -> redis_lib.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


CODE_TTL = 600  # 10 minutes


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
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _redis().setex(f"mcp_code:{code}", CODE_TTL, json.dumps(data))


def consume_auth_code(code: str) -> dict | None:
    r = _redis()
    key = f"mcp_code:{code}"
    raw = r.get(key)
    if not raw:
        return None
    r.delete(key)
    return json.loads(raw)


def verify_pkce(code_verifier: str, code_challenge: str, method: str) -> bool:
    if method == "S256":
        digest = hashlib.sha256(code_verifier.encode()).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        return expected == code_challenge
    if method == "plain":
        return code_verifier == code_challenge
    return False
