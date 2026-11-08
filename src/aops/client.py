"""The CLI side of the dbx edition: requests to the aops server with the user's Databricks login."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from typing import Any

from .project import Project


class ServerError(Exception):
    def __init__(self, status: int, body: dict[str, Any]):
        detail = body.get("title") or body.get("detail") or str(body)
        super().__init__(detail)
        self.status, self.body = status, body


class Server:
    def __init__(self, project: Project | None = None, *, url: str | None = None, profile: str | None = None):
        dbx = project.dbx if project else {}
        self.url = (url or os.environ.get("AOPS_SERVER") or dbx.get("server") or "").rstrip("/")
        self.profile = profile or os.environ.get("AOPS_PROFILE") or dbx.get("profile") or None
        if not self.url:
            raise ValueError("aops 서버 주소가 없습니다. aops.toml [dbx] server 또는 AOPS_SERVER를 정하세요")

    def _headers(self) -> dict[str, str]:
        from databricks.sdk import WorkspaceClient

        return WorkspaceClient(profile=self.profile).config.authenticate()

    def request(self, method: str, path: str, *, body: Any = None, data: bytes | None = None,
                content_type: str | None = None, raw: bool = False) -> Any:
        headers = dict(self._headers())
        if body is not None:
            data, content_type = json.dumps(body).encode(), "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(f"{self.url}/api/v1{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                payload = resp.read()
                return payload if raw else (json.loads(payload) if payload else None)
        except urllib.error.HTTPError as error:
            text = error.read()
            try:
                problem = json.loads(text)
            except ValueError:
                problem = {"title": text.decode(errors="replace")[:300]}
            raise ServerError(error.code, problem) from None

    def upload(self, path: str, fields: dict[str, str | None], file_field: str, filename: str, content: bytes) -> Any:
        boundary = uuid.uuid4().hex
        parts = []
        for key, value in fields.items():
            if value is not None:
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode())
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
                     "Content-Type: application/zip\r\n\r\n".encode() + content + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        return self.request("POST", path, data=b"".join(parts), content_type=f"multipart/form-data; boundary={boundary}")
