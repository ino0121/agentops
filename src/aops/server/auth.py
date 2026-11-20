"""Browser login for an aops server outside Databricks Apps: Databricks OAuth (authorization code + PKCE).

Databricks Apps logs people in itself and forwards their token. A server in a container (or one PC server for
several people) does the same here, with a custom OAuth app ("app connection") of the Databricks account:

- `GET /auth/login`: to the workspace's `/oidc/v1/authorize` (PKCE S256 and a random state, kept in a short
  encrypted cookie until the callback)
- `GET /auth/callback`: the code for tokens at `/oidc/v1/token`. The refresh token goes into an encrypted
  HttpOnly cookie (`aops_session`); the access token stays in this server's memory and is refreshed from the
  cookie when it runs out, so any replica can serve the session. Nothing is stored in a database.
- `POST /auth/logout`: the cookie is cleared. `GET /auth/signed-out` says so and offers to log in again (the
  Databricks login of the browser stays, so going straight to /auth/login would let the person right back in).

Who the person is and what they may do stays as everywhere else: the user's own token, SCIM /Me (email and
Databricks groups), roles from those groups and the policy. A request that brings a bearer token (the CLI,
another service) does not use the cookie. A request that uses the cookie and changes something must come from
this server's own origin (no cross-site requests).

Settings, from the environment:
- `AOPS_OAUTH_CLIENT_ID`: the app connection's client ID (turns the login on)
- `AOPS_OAUTH_CLIENT_SECRET`: its secret, for a confidential client (public clients use PKCE alone)
- `AOPS_PUBLIC_URL`: the address people open (https://aops.example.com). The redirect URL is <it>/auth/callback
- `AOPS_SESSION_KEY`: the cookie key (a Fernet key: `python -c "from cryptography.fernet import Fernet;
  print(Fernet.generate_key().decode())"`). A new key logs everyone out
- `AOPS_OAUTH_SCOPES` (default `all-apis offline_access`), `AOPS_SESSION_DAYS` (default 7, the refresh token's
  default life)
- `AOPS_OAUTH_HOST`: where `/oidc/v1/authorize` and `/oidc/v1/token` are, when not the workspace itself. The account is
  always checked at the workspace (SCIM /Me)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

SESSION_COOKIE = "aops_session"
LOGIN_COOKIE = "aops_login"
LOGIN_MAX_AGE = 600  # seconds between /auth/login and the callback
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
EARLY = 60  # an access token is refreshed this many seconds before it runs out


class AuthError(Exception):
    """The OAuth server refused (a code, a refresh token) or could not be reached."""


@dataclass(frozen=True)
class OAuth:
    host: str  # the OAuth server (the workspace unless AOPS_OAUTH_HOST)
    client_id: str
    client_secret: str | None
    public_url: str
    key: bytes
    scopes: str = "all-apis offline_access"
    session_days: int = 7
    workspace: str = ""  # where the account is checked (SCIM /Me); the OAuth server's address when empty

    @classmethod
    def from_env(cls) -> OAuth | None:
        """The login settings, or None: not asked for, or inside Databricks Apps (which logs people in itself)."""
        client_id = (os.environ.get("AOPS_OAUTH_CLIENT_ID") or "").strip()
        if not client_id or os.environ.get("DATABRICKS_APP_NAME"):
            return None
        public = (os.environ.get("AOPS_PUBLIC_URL") or "").strip().rstrip("/")
        key = (os.environ.get("AOPS_SESSION_KEY") or "").strip().encode()
        workspace = workspace_host()
        host = (os.environ.get("AOPS_OAUTH_HOST") or "").strip().rstrip("/") or workspace
        problems = []
        parsed = urllib.parse.urlparse(public)
        local = parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")
        if not (parsed.scheme == "https" or local) or not parsed.netloc:
            problems.append("AOPS_PUBLIC_URL은 https:// 주소입니다 (내 PC 시험만 http://localhost)")
        if not workspace:
            problems.append("워크스페이스 주소가 없습니다 (DATABRICKS_HOST 또는 AOPS_PROFILE)")
        try:
            from cryptography.fernet import Fernet

            Fernet(key)
        except Exception:
            problems.append("AOPS_SESSION_KEY는 Fernet 키입니다 (python -c \"from cryptography.fernet import Fernet; "
                            "print(Fernet.generate_key().decode())\")")
        if problems:
            raise RuntimeError("aops 로그인 설정: " + "; ".join(problems))
        return cls(host=host, client_id=client_id, client_secret=(os.environ.get("AOPS_OAUTH_CLIENT_SECRET") or "").strip() or None,
                   public_url=public, key=key, scopes=os.environ.get("AOPS_OAUTH_SCOPES") or "all-apis offline_access",
                   session_days=int(os.environ.get("AOPS_SESSION_DAYS") or 7), workspace=workspace)

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_url}/auth/callback"

    @property
    def origin(self) -> str:
        parsed = urllib.parse.urlparse(self.public_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def secure(self) -> bool:
        return self.public_url.startswith("https://")

    def cookie(self, response: Response, name: str, value: str, max_age: int, path: str = "/") -> None:
        response.set_cookie(name, value, max_age=max_age, path=path, httponly=True, secure=self.secure, samesite="lax")

    # ── the encrypted cookie ────────────────────────────────────────────────

    def seal(self, data: dict[str, Any]) -> str:
        from cryptography.fernet import Fernet

        return Fernet(self.key).encrypt(json.dumps(data).encode()).decode()

    def unseal(self, value: str | None, max_age: int) -> dict[str, Any] | None:
        """The cookie's content, or None when there is none, it was changed, or it is older than max_age."""
        if not value:
            return None
        from cryptography.fernet import Fernet, InvalidToken

        try:
            data = json.loads(Fernet(self.key).decrypt(value.encode(), ttl=max_age))
        except (InvalidToken, ValueError):
            return None
        return data if isinstance(data, dict) else None

    # ── the OAuth server ────────────────────────────────────────────────────

    def token_request(self, fields: dict[str, str]) -> dict[str, Any]:
        secret = (self.client_id, self.client_secret) if self.client_secret else None
        answer = post_form(f"{self.host}/oidc/v1/token", {**fields, "client_id": self.client_id}, secret)
        if not answer.get("access_token"):
            raise AuthError("토큰 응답에 access_token이 없습니다")
        return answer

    def access_token(self, session: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        """The session's access token (refreshed from its refresh token when needed), and the session to write
        back when the refresh token was replaced (single-use refresh tokens)."""
        sid = str(session.get("sid") or "")
        token = TOKENS.get(sid)
        if token:
            return token, None
        with TOKENS.lock(sid):  # one refresh per session at a time (a single-use refresh token works once)
            token = TOKENS.get(sid)
            if token:
                return token, None
            if not session.get("rt"):
                raise AuthError("세션이 끝났습니다")
            answer = self.token_request({"grant_type": "refresh_token", "refresh_token": session["rt"]})
            TOKENS.put(sid, answer["access_token"], answer.get("expires_in"))
            replaced = answer.get("refresh_token")
            return answer["access_token"], ({**session, "rt": replaced} if replaced and replaced != session["rt"] else None)

    def same_origin(self, request: Request) -> bool:
        origin = request.headers.get("origin")
        if origin:
            return origin.rstrip("/") == self.origin
        referer = request.headers.get("referer") or ""
        return referer == self.origin or referer.startswith(self.origin + "/")


def workspace_host() -> str:
    host = os.environ.get("DATABRICKS_HOST") or ""
    if not host and os.environ.get("AOPS_PROFILE"):
        from databricks.sdk.config import Config

        host = Config(profile=os.environ["AOPS_PROFILE"]).host or ""
    host = host.strip().rstrip("/")
    return host if not host or host.startswith("http") else f"https://{host}"


def post_form(url: str, fields: dict[str, str], basic: tuple[str, str] | None = None) -> dict[str, Any]:
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    if basic:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{basic[0]}:{basic[1]}".encode()).decode()
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as error:
        raise AuthError(f"토큰 요청이 거절됐습니다 ({error.code}): {error.read().decode(errors='replace')[:300]}") from None
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise AuthError(f"OAuth 서버에 닿지 못했습니다: {error}") from None


def whoami(host: str, token: str) -> str:
    """The token's account (SCIM /Me), to check a fresh login before the session is made."""
    req = urllib.request.Request(f"{host}/api/2.0/preview/scim/v2/Me", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return str(json.loads(resp.read()).get("userName") or "")
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise AuthError(f"로그인한 계정을 확인하지 못했습니다: {error}") from None


class Tokens:
    """Access tokens by session, in this server's memory (a restart or another replica refreshes from the cookie)."""

    def __init__(self, size: int = 5000):
        self.size = size
        self._items: dict[str, tuple[str, float]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, sid: str) -> str | None:
        with self._guard:
            hit = self._items.get(sid)
        return hit[0] if hit and hit[1] - EARLY > time.time() else None

    def put(self, sid: str, token: str, expires_in: Any) -> None:
        with self._guard:
            if len(self._items) >= self.size and sid not in self._items:
                self._items.pop(next(iter(self._items)))
            self._items[sid] = (token, time.time() + float(expires_in or 3600))

    def drop(self, sid: str) -> None:
        with self._guard:
            self._items.pop(sid, None)
            self._locks.pop(sid, None)

    def lock(self, sid: str) -> threading.Lock:
        with self._guard:
            if len(self._locks) >= self.size and sid not in self._locks:
                self._locks.clear()
            return self._locks.setdefault(sid, threading.Lock())


TOKENS = Tokens()


def safe_next(value: str | None) -> str:
    """Where to go after the login: a path on this server only."""
    value = value or "/"
    return value if value.startswith("/") and not value.startswith("//") and "\\" not in value else "/"


def _problem(status: int, code: str, title: str) -> JSONResponse:
    from .common import Problem

    return JSONResponse(Problem(title=title, status=status, code=code).model_dump(), status_code=status,
                        media_type="application/problem+json")


def _page(status: int, message: str, title: str = "aops 로그인") -> HTMLResponse:
    body = (f"<!doctype html><meta charset=utf-8><title>{html.escape(title)}</title><body style='font-family:sans-serif;margin:48px'>"
            f"<h2>{html.escape(title)}</h2><p>{html.escape(message)}</p><p><a href='/auth/login'>다시 로그인</a></p></body>")
    return HTMLResponse(body, status_code=status)


async def middleware(request: Request, call_next: Any) -> Response:
    """For API calls without a bearer token: the session cookie's user token (refreshed when needed)."""
    oauth: OAuth | None = getattr(request.app.state, "oauth", None)
    if oauth is None or not request.url.path.startswith("/api/") or request.headers.get("authorization"):
        return await call_next(request)
    session = oauth.unseal(request.cookies.get(SESSION_COOKIE), oauth.session_days * 86400)
    replaced, ended = None, False
    if session:
        if request.method in UNSAFE and not oauth.same_origin(request):
            return _problem(403, "cross_origin", "다른 사이트에서 온 요청은 받지 않습니다")
        try:
            token, replaced = await run_in_threadpool(oauth.access_token, session)
            request.state.session_token = token
        except AuthError:
            ended = True  # the refresh token no longer works: the person logs in again
    response = await call_next(request)
    if replaced:
        oauth.cookie(response, SESSION_COOKIE, oauth.seal(replaced), oauth.session_days * 86400)
    if ended:
        response.delete_cookie(SESSION_COOKIE, path="/")
    return response


router = APIRouter(include_in_schema=False)


def _oauth(request: Request) -> OAuth:
    oauth = getattr(request.app.state, "oauth", None)
    if oauth is None:
        raise RuntimeError("login is off")
    return oauth


@router.get("/auth/login")
def login(request: Request, next: str = "/") -> Response:
    oauth = _oauth(request)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    query = urllib.parse.urlencode({"client_id": oauth.client_id, "redirect_uri": oauth.redirect_uri, "response_type": "code",
                                    "scope": oauth.scopes, "state": state, "code_challenge": challenge,
                                    "code_challenge_method": "S256"})
    response = RedirectResponse(f"{oauth.host}/oidc/v1/authorize?{query}", status_code=302)
    oauth.cookie(response, LOGIN_COOKIE, oauth.seal({"state": state, "verifier": verifier, "next": safe_next(next)}),
                 LOGIN_MAX_AGE, path="/auth")
    return response


@router.get("/auth/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
             error_description: str | None = None) -> Response:
    oauth = _oauth(request)
    if error:
        return _page(400, f"로그인하지 못했습니다: {error_description or error}")
    pending = oauth.unseal(request.cookies.get(LOGIN_COOKIE), LOGIN_MAX_AGE)
    if not pending or not code or not state or not hmac.compare_digest(state, str(pending.get("state") or "")):
        return _page(400, "로그인 요청이 맞지 않습니다 (시간이 지났거나 다른 창에서 시작했습니다)")
    try:
        answer = oauth.token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": oauth.redirect_uri,
                                      "code_verifier": pending["verifier"], "scope": oauth.scopes})
        email = whoami(oauth.workspace or oauth.host, answer["access_token"])
    except AuthError as failure:
        return _page(502, str(failure))
    sid = secrets.token_urlsafe(18)
    TOKENS.put(sid, answer["access_token"], answer.get("expires_in"))
    response = RedirectResponse(safe_next(pending.get("next")), status_code=302)
    oauth.cookie(response, SESSION_COOKIE, oauth.seal({"sid": sid, "rt": answer.get("refresh_token"), "email": email}),
                 oauth.session_days * 86400)
    response.delete_cookie(LOGIN_COOKIE, path="/auth")
    return response


@router.post("/auth/logout")
def logout(request: Request) -> Response:
    oauth = _oauth(request)
    if not oauth.same_origin(request):
        return _problem(403, "cross_origin", "다른 사이트에서 온 요청은 받지 않습니다")
    session = oauth.unseal(request.cookies.get(SESSION_COOKIE), oauth.session_days * 86400)
    if session:
        TOKENS.drop(str(session.get("sid") or ""))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/auth/signed-out")
def signed_out(request: Request) -> Response:
    _oauth(request)
    return _page(200, "aops에서 로그아웃했습니다. 브라우저의 Databricks 로그인은 그대로라, 다시 로그인하면 바로 들어옵니다.", "aops 로그아웃")
