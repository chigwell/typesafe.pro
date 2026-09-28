"""Public, cached use-case read API (in OpenAPI) and the bearer-protected content write API."""

import hashlib
import json
from secrets import compare_digest
from typing import Annotated, Literal

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.responses import JSONResponse, Response

from .auth import bearer, client_ip, digest
from .content_store import (
    SLUG,
    ContentError,
    ContentStore,
    ResponseCache,
    cached,
    preview_token,
    valid_preview,
)
from .seo import RunReport, SeoJournal
from .use_case_schema import Page

PUBLIC_CACHE = "public, max-age=60, s-maxage=300, stale-while-revalidate=600"
Slug = Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=120)]


# ----- response models (documented in /openapi.json) ------------------------------------


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategoryRef(Model):
    slug: str
    name: str


class TagRef(Model):
    slug: str
    name: str


class UseCaseCard(Model):
    slug: str
    title: str
    summary: str
    industry: str
    audience: str
    task_type: str
    question_types: list[Literal["choice", "noul", "score"]]
    has_demo: bool
    category: CategoryRef | None
    tags: list[TagRef]
    published_at: str | None
    updated_at: str


class UseCaseList(Model):
    items: list[UseCaseCard]
    total: int
    page: int
    page_size: int


class UseCaseDetail(UseCaseCard):
    status: Literal["draft", "published"]
    page: dict = Field(description="The complete verified page: prose, examples, demo.")
    related: list[UseCaseCard]


class CategoryFacet(Model):
    slug: str
    name: str
    description: str
    count: int


class TagFacet(Model):
    slug: str
    name: str
    count: int


class Facets(Model):
    total: int
    categories: list[CategoryFacet]
    tags: list[TagFacet]


class SitemapEntry(Model):
    slug: str
    updated_at: str


class Sitemap(Model):
    items: list[SitemapEntry]
    total: int
    chunks: int
    chunk: int


class ApiError(Model):
    detail: str


# ----- helpers ---------------------------------------------------------------------------


def etag_response(request: Request, body: bytes, cache_control: str = PUBLIC_CACHE) -> Response:
    tag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
    headers = {"Cache-Control": cache_control, "ETag": tag, "Vary": "Accept-Encoding"}
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)


async def read_limit(request: Request):
    state = request.app.state
    config = state.settings
    ip_hash = digest(
        config.hash_secret, client_ip(request.scope, config.trusted_proxies).encode(), "content"
    )
    try:
        retry = await state.limiter.content_read_retry(ip_hash)
    except Exception:
        raise HTTPException(
            503, "Content temporarily unavailable", headers={"Retry-After": "5"}
        ) from None
    if retry:
        raise HTTPException(429, "Too many requests", headers={"Retry-After": str(retry)})


async def serve(request: Request, key, producer, *, limit=True, cache_control=PUBLIC_CACHE):
    state = request.app.state
    cache: ResponseCache = state.content_cache
    body = cache.get(key)
    if body is None:
        # Only cache misses reach Postgres, so only they spend the per-IP read budget.
        if limit:
            await read_limit(request)
        try:
            body = await cached(state, key, producer)
        except LookupError:
            raise HTTPException(404, "Use case not found") from None
        except (asyncpg.PostgresError, OSError, TimeoutError):
            raise HTTPException(
                503, "Content temporarily unavailable", headers={"Retry-After": "5"}
            ) from None
    return etag_response(request, body, cache_control)


def invalidate(request: Request):
    request.app.state.content_cache.invalidate()


def require_content_token(request: Request):
    candidate = bearer(request.scope["headers"])
    tokens = request.app.state.settings.content_tokens
    if not candidate or not tokens or not any(compare_digest(candidate, t) for t in tokens):
        raise HTTPException(401, "Content token required")


# ----- public router ---------------------------------------------------------------------


def public_content_router():
    router = APIRouter(prefix="/v1", tags=["use-cases"])
    errors = {404: {"model": ApiError}, 429: {"model": ApiError}, 503: {"model": ApiError}}

    @router.get(
        "/use-cases",
        response_model=UseCaseList,
        responses=errors,
        summary="Search and filter published use cases",
    )
    async def list_use_cases(
        request: Request,
        q: Annotated[str | None, Query(max_length=200, description="Full-text search")] = None,
        category: Annotated[str | None, Query(max_length=64, pattern=SLUG.pattern)] = None,
        tag: Annotated[str | None, Query(max_length=48, pattern=SLUG.pattern)] = None,
        page: Annotated[int, Query(ge=1, le=500)] = 1,
        page_size: Annotated[int, Query(ge=1, le=48)] = 24,
    ):
        query = " ".join((q or "").split()) or None
        key = ("list", query, category, tag, page, page_size)
        store = ContentStore(request.app.state.store)
        return await serve(
            request,
            key,
            lambda: store.listing(
                q=query, category=category, tag=tag, page=page, page_size=page_size
            ),
        )

    @router.get(
        "/use-case-facets", response_model=Facets, responses=errors, summary="Filter options"
    )
    async def facets(request: Request):
        store = ContentStore(request.app.state.store)
        return await serve(request, ("facets",), store.facets)

    @router.get(
        "/use-cases-sitemap", response_model=Sitemap, responses=errors, summary="Slugs for sitemaps"
    )
    async def sitemap(request: Request, chunk: Annotated[int, Query(ge=0, le=1000)] = 0):
        store = ContentStore(request.app.state.store)
        return await serve(request, ("sitemap", chunk), lambda: store.sitemap(chunk))

    @router.get(
        "/use-cases/{slug}",
        response_model=UseCaseDetail,
        responses=errors,
        summary="One published use case",
    )
    async def detail(request: Request, slug: Slug):
        store = ContentStore(request.app.state.store)

        async def produce():
            value = await store.detail(slug)
            if value is None:
                raise LookupError(slug)
            return value

        return await serve(request, ("detail", slug), produce)

    @router.get(
        "/use-cases/preview/{slug}",
        response_model=UseCaseDetail,
        responses=errors,
        summary="A draft for review (signed preview token)",
    )
    async def preview(request: Request, slug: Slug, token: Annotated[str, Query(max_length=200)]):
        if not valid_preview(request.app.state.settings.hash_secret, slug, token):
            raise HTTPException(404, "Use case not found")
        value = await ContentStore(request.app.state.store).detail(slug, include_drafts=True)
        if value is None:
            raise HTTPException(404, "Use case not found")
        return JSONResponse(
            value, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"}
        )

    return router


# ----- content write router (CLI) --------------------------------------------------------


class DraftBody(Model):
    page: dict
    status: Literal["draft", "published"] = "draft"
    category: str | None = Field(default=None, max_length=64)
    tags: list[Annotated[str, Field(max_length=48)]] = Field(default_factory=list, max_length=8)
    inspiration: dict | None = None
    novelty: float | None = Field(default=None, ge=0, le=1)
    published_at: str | None = None


class SkipBody(Model):
    fingerprint: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    slug: Annotated[str, Field(max_length=120)]
    summary: Annotated[str, Field(max_length=800)]
    task_type: Annotated[str, Field(max_length=80)]
    decision: Annotated[str, Field(max_length=800)]
    reason: Annotated[str, Field(max_length=800)] = ""


async def read_json(request: Request, limit=2 * 1024 * 1024):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise HTTPException(413, "Request too large")
    try:
        return json.loads(body)
    except ValueError:
        raise HTTPException(400, "Invalid JSON") from None


def content_admin_router():
    router = APIRouter(prefix="/admin/api/content", dependencies=[Depends(require_content_token)])

    def failure(exc: ContentError):
        return HTTPException(exc.status, exc.detail)

    @router.get("/use-cases")
    async def compact(request: Request):
        return {"items": await ContentStore(request.app.state.store).compact()}

    @router.get("/drafts")
    async def drafts(request: Request):
        return {"items": await ContentStore(request.app.state.store).drafts()}

    @router.get("/categories")
    async def categories(request: Request):
        return {"items": await ContentStore(request.app.state.store).categories()}

    @router.put("/use-cases/{slug}")
    async def put_use_case(request: Request, slug: Slug):
        from datetime import datetime

        try:
            body = DraftBody.model_validate(await read_json(request))
            page = Page.model_validate(body.page)
        except ValidationError as exc:
            first = exc.errors(include_input=False)[0]
            location = ".".join(str(part) for part in first["loc"])
            raise HTTPException(422, f"{location}: {first['msg']}") from None
        if page.slug != slug:
            raise HTTPException(422, "page.slug must match the URL")
        published_at = None
        if body.published_at:
            try:
                published_at = datetime.fromisoformat(body.published_at.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(422, "published_at must be ISO 8601") from None
        try:
            result = await ContentStore(request.app.state.store).upsert(
                page,
                status=body.status,
                category=body.category,
                tags=body.tags,
                inspiration=body.inspiration,
                novelty=body.novelty,
                published_at=published_at,
            )
        except ContentError as exc:
            raise failure(exc) from None
        invalidate(request)
        return result

    @router.post("/use-cases/{slug}/publish")
    async def publish(request: Request, slug: Slug):
        try:
            result = await ContentStore(request.app.state.store).set_status(slug, "published")
        except ContentError as exc:
            raise failure(exc) from None
        invalidate(request)
        return result

    @router.post("/use-cases/{slug}/archive")
    async def archive(request: Request, slug: Slug):
        try:
            result = await ContentStore(request.app.state.store).set_status(slug, "archived")
        except ContentError as exc:
            raise failure(exc) from None
        invalidate(request)
        return result

    @router.post("/use-cases/{slug}/preview-token")
    async def issue_preview(request: Request, slug: Slug):
        token = preview_token(request.app.state.settings.hash_secret, slug)
        return {"slug": slug, "token": token, "expires_in": 7200}

    @router.get("/skips")
    async def list_skips(request: Request):
        return {"items": await ContentStore(request.app.state.store).skips()}

    @router.post("/skips", status_code=201)
    async def add_skip(request: Request):
        try:
            item = SkipBody.model_validate(await read_json(request, 16 * 1024))
        except ValidationError:
            raise HTTPException(422, "Invalid skip") from None
        await ContentStore(request.app.state.store).add_skip(item.model_dump())
        return {"recorded": True}

    @router.post("/runs", status_code=201)
    async def record_run(request: Request):
        try:
            report = RunReport.model_validate(await read_json(request, 256 * 1024))
        except ValidationError:
            raise HTTPException(422, "Invalid run report") from None
        try:
            journal = SeoJournal(request.app.state.store)
            return await journal.record_run(report.model_dump(mode="json"))
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    return router
