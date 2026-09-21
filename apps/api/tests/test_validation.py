import json
from copy import deepcopy
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from conftest import VALID_REQUEST

from proxy.validation import InvalidRequest, validate_body


@pytest.mark.parametrize("state", ["", {}, [], {"nested": [None, True, 1, 1.5]}])
@pytest.mark.parametrize(
    "question",
    [
        {"type": "noul", "instructions": "?"},
        {"type": "noul", "instructions": {}, "criteria": {"true": [], "false": {}}},
        {"type": "noul", "instructions": [], "criteria": {"extension": None}},
        {"type": "choice", "instructions": "?", "criteria": {"a": None}},
        {"type": "choice", "instructions": [], "criteria": {str(i): {} for i in range(255)}},
        {"type": "score", "instructions": {}, "criteria": ["", []]},
        {"type": "score", "instructions": "?", "criteria": [{}] * 10},
    ],
)
def test_supported_schema_and_extensions(state, question):
    body = VALID_REQUEST | {
        "model": "future-model",
        "state": state,
        "questions": {"x": question | {"extension": True}},
        "extension": {"arbitrary": True},
    }
    validate_body(json.dumps(body).encode())


@pytest.mark.parametrize(
    "body,path",
    [
        ([], []),
        ({}, ["model"]),
        (VALID_REQUEST | {"model": 1}, ["model"]),
        (VALID_REQUEST | {"state": None}, ["state"]),
        (VALID_REQUEST | {"state": False}, ["state"]),
        (VALID_REQUEST | {"state": 1}, ["state"]),
        (VALID_REQUEST | {"questions": []}, ["questions"]),
        (VALID_REQUEST | {"questions": {"x": None}}, ["questions", "x"]),
    ],
)
def test_invalid_top_level(body, path):
    with pytest.raises(InvalidRequest) as exc:
        validate_body(json.dumps(body).encode())
    assert exc.value.status == 422
    assert exc.value.details["path"] == path


@pytest.mark.parametrize(
    "question,field",
    [
        ({}, "type"),
        ({"type": {}}, "type"),
        ({"type": "unknown"}, "type"),
        ({"type": "noul"}, "instructions"),
        ({"type": "noul", "instructions": None}, "instructions"),
        ({"type": "noul", "instructions": False}, "instructions"),
        ({"type": "noul", "instructions": "?", "criteria": None}, "criteria"),
        ({"type": "noul", "instructions": "?", "criteria": {"true": None}}, "criteria"),
        ({"type": "noul", "instructions": "?", "criteria": {"false": 1}}, "criteria"),
        ({"type": "choice", "instructions": "?"}, "criteria"),
        ({"type": "choice", "instructions": "?", "criteria": {}}, "criteria"),
        ({"type": "choice", "instructions": "?", "criteria": {"a": False}}, "criteria"),
        (
            {
                "type": "choice",
                "instructions": "?",
                "criteria": dict.fromkeys(map(str, range(256))),
            },
            "criteria",
        ),
        ({"type": "score", "instructions": "?"}, "criteria"),
        ({"type": "score", "instructions": "?", "criteria": {}}, "criteria"),
        ({"type": "score", "instructions": "?", "criteria": [""]}, "criteria"),
        ({"type": "score", "instructions": "?", "criteria": [""] * 11}, "criteria"),
        ({"type": "score", "instructions": "?", "criteria": ["", None]}, "criteria"),
    ],
)
def test_invalid_questions(question, field):
    with pytest.raises(InvalidRequest) as exc:
        validate_body(json.dumps(VALID_REQUEST | {"questions": {"x": question}}).encode())
    assert exc.value.code == "invalid_request"
    assert exc.value.details["path"][:3] == ["questions", "x", field]


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"\xff",
        b'{"a":1,"a":2}',
        b'{"a":{"b":1,"b":2}}',
        b'{"a":NaN}',
        b'{"a":Infinity}',
        b'{"a":-Infinity}',
        b'{"a":1e999}',
        b"[" * 2000,
    ],
)
def test_invalid_json(body):
    with pytest.raises(InvalidRequest) as exc:
        validate_body(body)
    assert exc.value.code == "invalid_json" and exc.value.status == 400


@pytest.mark.parametrize(
    "path,method,status,code",
    [
        (path, "GET", 404, "endpoint_not_found")
        for path in (
            "/",
            "/favicon.ico",
            "/.env",
            "/.env.test.local",
            "/.envrc",
            "/bot-connect.js",
            "/v1/systemone/",
            "/v1/systemone/extra",
            "/v1%2Fother",
        )
    ]
    + [("/", "PROPFIND", 404, "endpoint_not_found")]
    + [
        ("/v1/systemone", method, 405, "method_not_allowed")
        for method in ("GET", "HEAD", "PATCH", "DELETE", "OPTIONS", "CUSTOM")
    ]
    + [("/health", "POST", 405, "method_not_allowed")],
)
async def test_route_rejection_before_body_or_admission(
    path, method, status, code, client_for, monkeypatch, store
):
    async with client_for(lambda req: pytest.fail("Reached upstream")) as client:
        state = client.app.state
        admission = AsyncMock(side_effect=AssertionError("Admission called"))
        budget = Mock(side_effect=AssertionError("Budget claimed"))
        monkeypatch.setattr("proxy.main.authenticate", admission)
        monkeypatch.setattr(state.budget, "enter", budget)
        monkeypatch.setattr(state.scheduler, "acquire", admission)

        async def unread_body():
            pytest.fail("Read rejected request body")
            yield b"unread"

        result = await client.request(method, path, content=unread_body())
        assert result.status_code == status
        if method != "HEAD":
            assert result.json() == {"error": code}
        if status == 405:
            assert result.headers["allow"] == ("GET" if path == "/health" else "POST, OPTIONS")
        assert "retry-after" not in result.headers
        assert result.headers["cache-control"] == "no-store"
        assert result.headers["x-request-id"]
        assert result.headers["access-control-allow-origin"] == "*"
        admission.assert_not_called()
        budget.assert_not_called()
    event = await store.pool.fetchrow("SELECT * FROM proxy_error_events")
    assert event["error_code"] == code and event["client_tier"] == "unknown"
    assert event["upstream_status"] is event["upstream_ms"] is event["master_key_id"] is None
    assert event["queue_ms"] == event["request_bytes"] == 0


@pytest.mark.parametrize(
    "headers,body,status,code",
    [
        ({}, b"{}", 415, "unsupported_media_type"),
        ({"Content-Type": "text/plain"}, b"{}", 415, "unsupported_media_type"),
        (
            {"Content-Type": "application/json", "Content-Encoding": "gzip"},
            b"{}",
            415,
            "unsupported_media_type",
        ),
        (
            [("Content-Type", "application/json"), ("Content-Type", "application/json")],
            b"{}",
            415,
            "unsupported_media_type",
        ),
        ({"Content-Type": "application/json"}, b"not-json-sensitive", 400, "invalid_json"),
        ({"Content-Type": "application/json"}, b'{"model":"sensitive"}', 422, "invalid_request"),
    ],
)
async def test_body_rejection_never_reserves_master(
    headers, body, status, code, client_for, monkeypatch, store
):
    async with client_for(lambda req: pytest.fail("Reached upstream")) as client:
        acquire = AsyncMock(side_effect=AssertionError("Master reserved"))
        monkeypatch.setattr(client.app.state.scheduler, "acquire", acquire)
        result = await client.post("/v1/systemone", headers=headers, content=body)
        assert result.status_code == status and result.json()["error"] == code
        assert "sensitive" not in result.text
        assert "retry-after" not in result.headers
        assert client.app.state.budget.bytes == client.app.state.budget.requests == 0
        acquire.assert_not_called()
        if status == 422:
            assert result.json()["details"] == {
                "path": ["state"],
                "reason": "Expected string, object or array",
            }
    event = await store.pool.fetchrow("SELECT * FROM proxy_error_events")
    assert event["master_key_id"] is event["upstream_status"] is event["raw_response"] is None
    assert event["error_code"] == code
    assert "sensitive" not in str(dict(event))


@pytest.mark.parametrize(
    "path,requested,status",
    [
        ("/v1/systemone", "POST", 204),
        ("/v1/systemone", "DELETE", 405),
        ("/.env", "POST", 404),
        ("/v1/systemone/", "POST", 404),
    ],
)
async def test_preflight_allowlist(path, requested, status, client_for):
    async with client_for(lambda req: pytest.fail("Reached upstream")) as client:
        result = await client.options(
            path,
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": requested,
            },
        )
    assert result.status_code == status
    if status == 204:
        assert result.headers["access-control-allow-methods"] == "POST, OPTIONS"


async def test_structured_payload_bytes_and_extensions_reach_upstream(client_for):
    payload = deepcopy(VALID_REQUEST)
    payload["questions"] = {
        "n": {"type": "noul", "instructions": {"question": "?"}},
        "c": {"type": "choice", "instructions": ["?"], "criteria": {"a": None}},
        "s": {"type": "score", "instructions": "?", "criteria": [[], {}]},
    }
    payload["extra"] = True
    raw = json.dumps(payload, indent=2).encode() + b"\n"
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(422, stream=httpx.ByteStream(b'{"error":"model unavailable"}'))

    async with client_for(handler) as client:
        result = await client.post(
            "/v1/%73ystemone?extra=one&extra=two",
            content=raw,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Content-Encoding": "identity",
            },
        )
    assert result.status_code == 422
    assert len(seen) == 1 and seen[0].content == raw
    assert seen[0].url.raw_path == b"/v1/%73ystemone?extra=one&extra=two"


async def test_validation_error_with_escaped_field_name(client_for):
    body = json.dumps(VALID_REQUEST | {"questions": {"\ud800": None}}).encode()
    async with client_for(lambda req: pytest.fail("Reached upstream")) as client:
        result = await client.post(
            "/v1/systemone", content=body, headers={"Content-Type": "application/json"}
        )
        assert result.status_code == 422
        assert result.json()["details"]["path"] == ["questions", "\ud800"]
        assert client.app.state.budget.bytes == client.app.state.budget.requests == 0
