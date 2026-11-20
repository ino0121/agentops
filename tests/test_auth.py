"""The browser login of a server outside Databricks Apps (server/auth.py), against a fake OAuth server."""

import base64
import hashlib
import urllib.parse
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("cryptography")

from cryptography.fernet import Fernet  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from aops.dbx.service import Caller  # noqa: E402
from aops.server import auth, create_app  # noqa: E402

PUBLIC = "https://aops.example.com"


@pytest.fixture
def server(monkeypatch):
    monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
    monkeypatch.delenv("AOPS_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("AOPS_OAUTH_CLIENT_ID", "aops-client")
    monkeypatch.setenv("AOPS_PUBLIC_URL", PUBLIC)
    monkeypatch.setenv("AOPS_SESSION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("DATABRICKS_HOST", "https://ws.example.com")
    calls = []

    def token_endpoint(url, fields, basic=None):
        calls.append((url, dict(fields), basic))
        if fields["grant_type"] == "authorization_code":
            return {"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600}
        return {"access_token": f"at-{len(calls)}", "refresh_token": "rt-2", "expires_in": 3600}

    monkeypatch.setattr(auth, "post_form", token_endpoint)
    monkeypatch.setattr(auth, "whoami", lambda host, token: "dev@x.com")
    monkeypatch.setattr(auth, "TOKENS", auth.Tokens())
    seen = []
    svc = SimpleNamespace(config=SimpleNamespace(profile=None),
                          identify=lambda token, email: seen.append(token) or Caller("dev@x.com", token=token, groups=["admins"]),
                          me=lambda caller: {"user": caller.email, "groups": caller.groups, "roles": ["developer", "admin"]})
    from aops.server import dbx

    monkeypatch.setattr(dbx, "service_for", lambda command: svc)
    client = TestClient(create_app(edition="dbx"), base_url=PUBLIC, follow_redirects=False)
    return SimpleNamespace(client=client, calls=calls, seen=seen)


def logged_in(server, next_path="/#/agents"):
    start = server.client.get("/auth/login", params={"next": next_path})
    params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(start.headers["location"]).query))
    done = server.client.get("/auth/callback", params={"code": "the-code", "state": params["state"]})
    return start, params, done


def test_without_a_session_the_api_sends_people_to_the_login(server):
    answer = server.client.get("/api/v1/meta/me")
    assert answer.status_code == 401 and answer.json()["code"] == "login_required"
    assert answer.json()["data"] == {"login": "/auth/login"}


def test_login_goes_to_the_workspace_with_pkce_and_comes_back_with_a_session(server):
    start, params, done = logged_in(server)
    where = urllib.parse.urlparse(start.headers["location"])
    assert (where.netloc, where.path) == ("ws.example.com", "/oidc/v1/authorize")
    assert params["client_id"] == "aops-client" and params["redirect_uri"] == f"{PUBLIC}/auth/callback"
    assert params["code_challenge_method"] == "S256" and params["scope"] == "all-apis offline_access"
    url, fields, basic = server.calls[0]
    assert url == "https://ws.example.com/oidc/v1/token" and fields["grant_type"] == "authorization_code" and basic is None
    challenge = base64.urlsafe_b64encode(hashlib.sha256(fields["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert challenge == params["code_challenge"] and fields["code"] == "the-code"
    assert done.status_code == 302 and done.headers["location"] == "/#/agents"
    cookie = [c for c in done.headers.get_list("set-cookie") if c.startswith("aops_session=")][0].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    me = server.client.get("/api/v1/meta/me")
    assert me.status_code == 200 and me.json()["user"] == "dev@x.com" and me.json()["login"] == "oauth"
    assert server.seen[-1] == "at-1"  # the user's own token, not the server's


def test_a_callback_that_does_not_match_the_login_is_refused(server):
    server.client.get("/auth/login")
    assert server.client.get("/auth/callback", params={"code": "c", "state": "someone-else"}).status_code == 400
    assert server.client.get("/auth/callback", params={"error": "access_denied"}).status_code == 400
    assert server.calls == []


def test_only_paths_of_this_server_are_followed_after_the_login(server):
    _, _, done = logged_in(server, "//evil.example.com/x")
    assert done.headers["location"] == "/"
    assert auth.safe_next("https://evil.example.com") == "/" and auth.safe_next("/#/gates") == "/#/gates"


def test_cookie_requests_that_change_things_must_come_from_this_site(server):
    logged_in(server)
    foreign = server.client.post("/api/v1/meta/me", headers={"Origin": "https://evil.example.com"})
    assert foreign.status_code == 403 and foreign.json()["code"] == "cross_origin"
    assert server.client.post("/api/v1/meta/me", headers={"Origin": PUBLIC}).status_code != 403  # reaches the route
    bearer = server.client.post("/api/v1/meta/me", headers={"Origin": "https://evil.example.com", "Authorization": "Bearer x"})
    assert bearer.status_code != 403  # a bearer token is not a cookie: no cross-site risk


def test_another_replica_refreshes_the_token_and_keeps_a_new_refresh_token(server, monkeypatch):
    logged_in(server)
    monkeypatch.setattr(auth, "TOKENS", auth.Tokens())  # a restart, or another replica: no access token in memory
    me = server.client.get("/api/v1/meta/me")
    assert me.status_code == 200
    _, fields, _ = server.calls[-1]
    assert fields["grant_type"] == "refresh_token" and fields["refresh_token"] == "rt-1"
    assert any(c.startswith("aops_session=") for c in me.headers.get_list("set-cookie"))  # single-use: the new one
    monkeypatch.setattr(auth, "TOKENS", auth.Tokens())
    server.client.get("/api/v1/meta/me")
    assert server.calls[-1][1]["refresh_token"] == "rt-2"


def test_a_refresh_that_no_longer_works_ends_the_session(server, monkeypatch):
    logged_in(server)
    monkeypatch.setattr(auth, "TOKENS", auth.Tokens())

    def refused(url, fields, basic=None):
        raise auth.AuthError("invalid_grant")

    monkeypatch.setattr(auth, "post_form", refused)
    answer = server.client.get("/api/v1/meta/me")
    assert answer.status_code == 401 and answer.json()["code"] == "login_required"
    assert any(c.startswith('aops_session=""') or "max-age=0" in c.lower() for c in answer.headers.get_list("set-cookie"))


def test_logout_clears_the_session_and_only_from_this_site(server):
    logged_in(server)
    assert server.client.post("/auth/logout", headers={"Origin": "https://evil.example.com"}).status_code == 403
    out = server.client.post("/auth/logout", headers={"Origin": PUBLIC})
    assert out.status_code == 204
    page = server.client.get("/auth/signed-out")
    assert page.status_code == 200 and "로그아웃했습니다" in page.text and "/auth/login" in page.text
    server.client.cookies.clear()
    assert server.client.get("/api/v1/meta/me").status_code == 401


def test_a_changed_cookie_is_no_session(server):
    server.client.cookies.set("aops_session", "not-a-sealed-value", domain="aops.example.com")
    assert server.client.get("/api/v1/meta/me").status_code == 401


def test_a_bearer_token_is_used_as_it_is(server):
    me = server.client.get("/api/v1/meta/me", headers={"Authorization": "Bearer cli-token"})
    assert me.status_code == 200 and me.json()["login"] == "token" and server.seen[-1] == "cli-token"


def test_the_settings_are_checked(monkeypatch):
    monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
    monkeypatch.delenv("AOPS_OAUTH_CLIENT_ID", raising=False)
    assert auth.OAuth.from_env() is None  # no client: no login (bearer tokens and the PC profile as before)
    monkeypatch.setenv("AOPS_OAUTH_CLIENT_ID", "c")
    monkeypatch.setenv("DATABRICKS_HOST", "ws.example.com")
    monkeypatch.setenv("AOPS_PUBLIC_URL", "http://aops.example.com")
    monkeypatch.setenv("AOPS_SESSION_KEY", "short")
    with pytest.raises(RuntimeError) as error:
        auth.OAuth.from_env()
    assert "https://" in str(error.value) and "Fernet" in str(error.value)
    monkeypatch.setenv("AOPS_PUBLIC_URL", "http://localhost:8000")  # a PC try-out
    monkeypatch.setenv("AOPS_SESSION_KEY", Fernet.generate_key().decode())
    oauth = auth.OAuth.from_env()
    assert oauth.host == "https://ws.example.com" and oauth.redirect_uri == "http://localhost:8000/auth/callback" and not oauth.secure
    monkeypatch.setenv("DATABRICKS_APP_NAME", "aops-server")
    assert auth.OAuth.from_env() is None  # Databricks Apps logs people in itself


def test_the_token_and_account_calls_go_over_http(monkeypatch):
    """post_form and whoami against a real local HTTP server (the other tests replace them)."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    got = {}

    class Fake(BaseHTTPRequestHandler):
        def do_POST(self):
            got["auth"] = self.headers.get("Authorization")
            got["form"] = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers["Content-Length"])).decode()))
            self._json({"access_token": "real-at", "refresh_token": "real-rt", "expires_in": 3600})

        def do_GET(self):
            got["bearer"] = self.headers.get("Authorization")
            self._json({"userName": "dev@x.com"})

        def _json(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
        monkeypatch.setenv("AOPS_OAUTH_CLIENT_ID", "aops-client")
        monkeypatch.setenv("AOPS_OAUTH_CLIENT_SECRET", "s3cret")
        monkeypatch.setenv("AOPS_PUBLIC_URL", "http://localhost:8000")
        monkeypatch.setenv("AOPS_SESSION_KEY", Fernet.generate_key().decode())
        monkeypatch.setenv("DATABRICKS_HOST", f"http://127.0.0.1:{httpd.server_port}")
        monkeypatch.setattr(auth, "TOKENS", auth.Tokens())
        client = TestClient(create_app(edition="dbx"), base_url="http://localhost:8000", follow_redirects=False)
        start = client.get("/auth/login")
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(start.headers["location"]).query))["state"]
        done = client.get("/auth/callback", params={"code": "c1", "state": state})
        assert done.status_code == 302 and any(c.startswith("aops_session=") for c in done.headers.get_list("set-cookie"))
        assert got["auth"] == "Basic " + base64.b64encode(b"aops-client:s3cret").decode()  # a confidential client
        assert got["form"]["grant_type"] == "authorization_code" and got["form"]["code"] == "c1"
        assert got["bearer"] == "Bearer real-at"  # the account is checked with the user's new token
    finally:
        httpd.shutdown()


def test_the_oauth_server_can_be_apart_from_the_workspace(monkeypatch):
    monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
    monkeypatch.setenv("AOPS_OAUTH_CLIENT_ID", "c")
    monkeypatch.setenv("DATABRICKS_HOST", "https://ws.example.com")
    monkeypatch.setenv("AOPS_OAUTH_HOST", "https://login.example.com/")
    monkeypatch.setenv("AOPS_PUBLIC_URL", PUBLIC)
    monkeypatch.setenv("AOPS_SESSION_KEY", Fernet.generate_key().decode())
    oauth = auth.OAuth.from_env()
    assert (oauth.host, oauth.workspace) == ("https://login.example.com", "https://ws.example.com")
