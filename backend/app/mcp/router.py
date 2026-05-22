import json
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.mcp.oauth import consume_auth_code, generate_code, store_auth_code, verify_pkce
from app.mcp.tools import TOOLS, call_tool
from app.models.user import User
from app.services.auth_service import create_access_token, decode_access_token, verify_password

logger = logging.getLogger(__name__)
router = APIRouter(tags=["mcp"])


def _base_url(request: Request) -> str:
    if settings.MCP_BASE_URL:
        return settings.MCP_BASE_URL.rstrip("/")
    return str(request.base_url).rstrip("/")


# ─── OAuth: Authorization endpoint ───────────────────────────────────────────

@router.get("/oauth/authorize", response_class=HTMLResponse)
async def oauth_authorize_form(
    redirect_uri: str = "",
    state: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "S256",
    client_id: str = "",
    response_type: str = "code",
):
    return HTMLResponse(_login_html(redirect_uri, state, code_challenge, code_challenge_method, error=None))


@router.post("/oauth/authorize", response_class=HTMLResponse)
async def oauth_authorize_submit(
    email: str = Form(...),
    password: str = Form(...),
    redirect_uri: str = Form(...),
    state: str = Form(""),
    code_challenge: str = Form(""),
    code_challenge_method: str = Form("S256"),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email, User.is_active == True).first()
    if not user or not verify_password(password, user.password_hash):
        return HTMLResponse(
            _login_html(redirect_uri, state, code_challenge, code_challenge_method, error="Invalid email or password"),
            status_code=401,
        )

    code = generate_code()
    store_auth_code(
        code=code,
        user_id=str(user.id),
        redirect_uri=redirect_uri,
        code_challenge=code_challenge or None,
        code_challenge_method=code_challenge_method or None,
    )

    params = {"code": code}
    if state:
        params["state"] = state
    return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=302)


# ─── OAuth: Token endpoint ────────────────────────────────────────────────────

@router.post("/oauth/token")
async def oauth_token(request: Request, db: Session = Depends(get_db)):
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
    else:
        form = await request.form()
        body = dict(form)

    grant_type = body.get("grant_type")
    code = body.get("code")
    code_verifier = body.get("code_verifier", "")
    redirect_uri = body.get("redirect_uri", "")

    if grant_type != "authorization_code":
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)
    if not code:
        return JSONResponse({"error": "invalid_request", "error_description": "code required"}, status_code=400)

    code_data = consume_auth_code(code)
    if not code_data:
        return JSONResponse({"error": "invalid_grant", "error_description": "Code expired or invalid"}, status_code=400)

    if redirect_uri and redirect_uri != code_data.get("redirect_uri"):
        return JSONResponse({"error": "invalid_grant", "error_description": "redirect_uri mismatch"}, status_code=400)

    stored_challenge = code_data.get("code_challenge")
    if stored_challenge and code_verifier:
        method = code_data.get("code_challenge_method", "S256")
        if not verify_pkce(code_verifier, stored_challenge, method):
            return JSONResponse({"error": "invalid_grant", "error_description": "PKCE verification failed"}, status_code=400)

    user = db.query(User).filter(User.id == code_data["user_id"], User.is_active == True).first()
    if not user:
        return JSONResponse({"error": "invalid_grant", "error_description": "User not found"}, status_code=400)

    token = create_access_token(str(user.id), user.roles or [])
    return JSONResponse({
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.JWT_EXPIRE_HOURS * 3600,
    })


# ─── MCP: Streamable HTTP endpoint ───────────────────────────────────────────

@router.post("/mcp")
async def mcp_endpoint(request: Request, db: Session = Depends(get_db)):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Bearer realm="MEANDER Ads Platform"'},
        )

    payload = decode_access_token(auth_header[7:])
    if not payload:
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_jsonrpc_error(None, -32700, "Parse error"))

    if isinstance(body, list):
        responses = [r for msg in body if (r := _handle_rpc(msg, db)) is not None]
        return JSONResponse(responses)

    result = _handle_rpc(body, db)
    if result is None:
        return Response(status_code=202)
    return JSONResponse(result)


def _handle_rpc(msg: dict, db: Session) -> dict | None:
    rpc_id = msg.get("id")
    method = msg.get("method", "")
    params = msg.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "MEANDER Ads Platform", "version": "1.0.0"},
            },
        }

    if method == "notifications/initialized":
        return None  # no response for notifications

    if method == "ping":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        try:
            data = call_tool(tool_name, arguments, db)
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(data, indent=2, default=str)}],
                    "isError": False,
                },
            }
        except ValueError as e:
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"content": [{"type": "text", "text": str(e)}], "isError": True},
            }
        except Exception as e:
            logger.exception("MCP tool error: %s", tool_name)
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"content": [{"type": "text", "text": f"Error querying data: {e}"}], "isError": True},
            }

    return _jsonrpc_error(rpc_id, -32601, f"Method not found: {method}")


def _jsonrpc_error(rpc_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


# ─── Login form HTML ──────────────────────────────────────────────────────────

def _login_html(
    redirect_uri: str,
    state: str,
    code_challenge: str,
    code_challenge_method: str,
    error: str | None,
) -> str:
    error_block = f'<div class="error">{error}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>MEANDER Ads — Sign In</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0 }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #0f1117;
      color: #e2e8f0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .card {{
      background: #1a1f2e;
      border: 1px solid #2d3448;
      border-radius: 12px;
      padding: 40px;
      width: 100%;
      max-width: 400px;
    }}
    .logo {{
      font-size: 12px;
      font-weight: 600;
      letter-spacing: 0.15em;
      text-transform: uppercase;
      color: #64748b;
      margin-bottom: 8px;
    }}
    h1 {{ font-size: 22px; font-weight: 600; color: #f1f5f9; margin-bottom: 4px }}
    .subtitle {{ font-size: 13px; color: #64748b; margin-bottom: 28px }}
    label {{ display: block; font-size: 13px; font-weight: 500; color: #94a3b8; margin-bottom: 6px }}
    input[type="email"], input[type="password"] {{
      width: 100%;
      padding: 10px 14px;
      background: #0f1117;
      border: 1px solid #2d3448;
      border-radius: 8px;
      color: #f1f5f9;
      font-size: 14px;
      margin-bottom: 18px;
      outline: none;
      transition: border-color 0.15s;
    }}
    input:focus {{ border-color: #4f8ef7 }}
    button {{
      width: 100%;
      padding: 11px;
      background: #4f8ef7;
      color: #fff;
      font-size: 14px;
      font-weight: 600;
      border: none;
      border-radius: 8px;
      cursor: pointer;
      transition: background 0.15s;
    }}
    button:hover {{ background: #3b7de8 }}
    .error {{
      background: #2d1b1b;
      border: 1px solid #7f1d1d;
      border-radius: 8px;
      padding: 10px 14px;
      font-size: 13px;
      color: #fca5a5;
      margin-bottom: 18px;
    }}
    .note {{
      margin-top: 20px;
      padding: 10px 14px;
      background: #0f1117;
      border: 1px solid #2d3448;
      border-radius: 8px;
      font-size: 12px;
      color: #64748b;
      line-height: 1.5;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">MEANDER Group</div>
    <h1>Sign in to Ads Platform</h1>
    <p class="subtitle">Connect Claude to your campaign data</p>
    {error_block}
    <form method="post" action="/oauth/authorize">
      <input type="hidden" name="redirect_uri" value="{redirect_uri}">
      <input type="hidden" name="state" value="{state}">
      <input type="hidden" name="code_challenge" value="{code_challenge}">
      <input type="hidden" name="code_challenge_method" value="{code_challenge_method}">
      <label for="email">Email</label>
      <input id="email" type="email" name="email" placeholder="you@meander.com" required autofocus>
      <label for="password">Password</label>
      <input id="password" type="password" name="password" placeholder="••••••••" required>
      <button type="submit">Sign in</button>
    </form>
    <div class="note">
      Claude will get read-only access to campaign metrics, spend, budgets, and country breakdowns.
    </div>
  </div>
</body>
</html>"""
