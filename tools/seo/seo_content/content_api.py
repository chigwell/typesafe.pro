"""HTTPS client for the typesafe.pro content API used by the review session."""

import os
from urllib.parse import quote

import httpx

from .errors import ContentApiError  # noqa: F401

DEFAULT_BASE = "https://api.typesafe.pro"


class ContentApi:
    def __init__(self, base=None, token=None, client=None, timeout=30):
        self.base = (base or os.environ.get("TYPESAFE_API_BASE") or DEFAULT_BASE).rstrip("/")
        self.token = token if token is not None else os.environ.get("TYPESAFE_CONTENT_TOKEN_1", "")
        if not self.token:
            raise ContentApiError("missing_content_token", retryable=False)
        if not self.base.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ContentApiError("content_api_must_use_https", retryable=False)
        self.client = client or httpx.Client(timeout=timeout, follow_redirects=False)

    def _call(self, method, path, **kwargs):
        try:
            response = self.client.request(
                method,
                self.base + "/admin/api/content" + path,
                headers={"Authorization": f"Bearer {self.token}"},
                **kwargs,
            )
        except httpx.HTTPError:
            raise ContentApiError("content_api_unreachable") from None
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", "")
            except ValueError:
                detail = ""
            retryable = response.status_code == 429 or response.status_code >= 500
            error = ContentApiError(
                f"content_api_http_{response.status_code}",
                status=response.status_code,
                retryable=retryable,
            )
            error.detail = str(detail)[:300] or None
            raise error
        return response.json()

    # ----- reads ----------------------------------------------------------------------

    def compact_pages(self) -> list[dict]:
        return self._call("GET", "/use-cases")["items"]

    def drafts(self) -> list[dict]:
        return self._call("GET", "/drafts")["items"]

    def categories(self) -> list[dict]:
        return self._call("GET", "/categories")["items"]

    def skips(self) -> list[dict]:
        return self._call("GET", "/skips")["items"]

    # ----- writes ---------------------------------------------------------------------

    def put(
        self,
        page: dict,
        *,
        status="draft",
        category=None,
        tags=(),
        meta=None,
        novelty=None,
        published_at=None,
    ) -> dict:
        body = {"page": page, "status": status, "category": category, "tags": list(tags)}
        if meta is not None:
            body["inspiration"] = meta
        if novelty is not None:
            body["novelty"] = novelty
        if published_at is not None:
            body["published_at"] = published_at
        return self._call("PUT", f"/use-cases/{quote(page['slug'])}", json=body)

    def publish(self, slug: str) -> dict:
        return self._call("POST", f"/use-cases/{quote(slug)}/publish")

    def archive(self, slug: str) -> dict:
        return self._call("POST", f"/use-cases/{quote(slug)}/archive")

    def preview_token(self, slug: str) -> str:
        return self._call("POST", f"/use-cases/{quote(slug)}/preview-token")["token"]

    def add_skip(self, item: dict) -> None:
        self._call("POST", "/skips", json=item)

    def record_run(self, report: dict) -> dict:
        return self._call("POST", "/runs", json=report)
