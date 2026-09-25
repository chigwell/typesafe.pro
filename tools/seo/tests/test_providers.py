import signal
import time

import httpx
import pytest

from seo_content.models import SEO, EvaluationRequest
from seo_content.providers import Budget, BudgetExhausted, ProviderError, Providers, StageError


def provider(monkeypatch, handler, budget=None):
    monkeypatch.setenv("LLM7_TOKEN", "test-only-secret")
    monkeypatch.setenv("TYPESAFE_ADMIN_API_TOKEN_1", "test-only-secret")
    return Providers(
        budget or Budget(), client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_format_and_schema_repairs_share_three_attempts(monkeypatch):
    payloads = []
    replies = [
        "No tags",
        '<json>{"title":"too short"}</json>',
        '<json>{"title":"A concrete developer tutorial", "description":'
        '"Learn a practical semantic routing workflow with three verified examples '
        'and clear implementation guidance."}</json>',
    ]

    def handler(request):
        payloads.append(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": replies.pop(0)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )

    instance = provider(monkeypatch, handler)
    result = instance.structured(SEO, "Make metadata", {})
    assert result.title == "A concrete developer tutorial"
    assert instance.budget.calls == 3 and instance.budget.input_tokens == 30
    assert b"validation errors" in payloads[-1]


@pytest.mark.parametrize("failure", ["format", "429", "timeout", "invalid_json"])
def test_network_and_format_failures_never_multiply_retries(monkeypatch, failure):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret from request must not escape")
        if failure == "429":
            return httpx.Response(429, text="secret diagnostic")
        content = "<json>{broken}</json>" if failure == "invalid_json" else "No match"
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr("seo_content.providers.time.sleep", lambda _: None)
    instance = provider(monkeypatch, handler)
    error = "llm_provider_unavailable" if failure in ("429", "timeout") else "llm_stage_failed"
    with pytest.raises(ProviderError, match=f"^{error}$"):
        instance.structured(SEO, "Make metadata", {})
    assert instance.budget.calls == 3


def test_budget_halts_even_when_llmatch_catches_exception(monkeypatch):
    def handler(request):
        return httpx.Response(429)

    instance = provider(monkeypatch, handler, Budget(max_calls=1))
    with pytest.raises(BudgetExhausted):
        instance.structured(SEO, "Make metadata", {})
    assert instance.budget.calls == 1


def test_jev_retries_and_body_validation(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"model": "jev-test", "answers": {}})

    instance = provider(monkeypatch, handler)
    with pytest.raises(StageError, match="invalid_jev_response"):
        instance.evaluate(
            EvaluationRequest(
                state="message", questions={"q": {"type": "noul", "instructions": "Is it urgent?"}}
            )
        )
    assert instance.budget.calls == 3


@pytest.mark.parametrize("status", [401, 403])
def test_invalid_credentials_are_never_retried(monkeypatch, status):
    instance = provider(monkeypatch, lambda request: httpx.Response(status))
    with pytest.raises(ProviderError, match=f"provider_http_{status}"):
        instance.structured(SEO, "Generate", {})
    assert instance.budget.calls == 1


def test_retry_after_respected_and_charged_to_time_budget(monkeypatch):
    waits = []
    monkeypatch.setattr("seo_content.providers.time.sleep", waits.append)
    instance = provider(
        monkeypatch, lambda request: httpx.Response(429, headers={"Retry-After": "7"})
    )
    with pytest.raises(ProviderError):
        instance.structured(SEO, "Generate", {})
    assert waits == [7, 7]
    assert instance.budget.calls == 3


def test_retry_after_exceeding_budget_stops_without_wait(monkeypatch):
    instance = provider(
        monkeypatch,
        lambda request: httpx.Response(429, headers={"Retry-After": "1000"}),
        Budget(max_seconds=30),
    )
    with pytest.raises(BudgetExhausted, match="retry_delay_exceeds_budget"):
        instance.structured(SEO, "Generate", {})
    assert instance.budget.calls == 1


class CountingStream(httpx.SyncByteStream):
    def __init__(self, *, pause=0, chunk=b"x" * 16_384, count=200):
        self.pause = pause
        self.chunk = chunk
        self.count = count
        self.consumed = 0
        self.closed = False

    def __iter__(self):
        for _ in range(self.count):
            if self.pause:
                time.sleep(self.pause)
            self.consumed += 1
            yield self.chunk

    def close(self):
        self.closed = True


def test_large_response_stops_reading_at_limit_and_closes(monkeypatch):
    stream = CountingStream()
    instance = provider(monkeypatch, lambda _: httpx.Response(200, stream=stream))
    with pytest.raises(ProviderError, match="^provider_response_too_large$"):
        instance.structured(SEO, "Generate", {})
    assert stream.closed and stream.consumed == 65
    assert instance.budget.calls == 1


def test_error_bodies_are_never_read(monkeypatch):
    stream = CountingStream()
    instance = provider(monkeypatch, lambda _: httpx.Response(401, stream=stream))
    with pytest.raises(ProviderError, match="^provider_http_401$"):
        instance.structured(SEO, "Generate", {})
    assert stream.closed and stream.consumed == 0


def test_rejects_compressed_stream_before_decompression(monkeypatch):
    stream = CountingStream()
    headers = []

    def handler(request):
        headers.append(request.headers["accept-encoding"])
        return httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=stream)

    instance = provider(monkeypatch, handler)
    with pytest.raises(ProviderError, match="^provider_content_encoding_unsupported$"):
        instance.structured(SEO, "Generate", {})
    assert headers == ["identity"]
    assert stream.closed and stream.consumed == 0


def test_overall_deadline_interrupts_a_continuously_trickling_body(monkeypatch):
    stream = CountingStream(pause=0.01, chunk=b" ", count=1000)
    updates = []
    budget = Budget(max_seconds=0.08, on_update=lambda: updates.append(True))
    instance = provider(monkeypatch, lambda _: httpx.Response(200, stream=stream), budget)
    started = time.monotonic()
    with pytest.raises(BudgetExhausted, match="^budget_exhausted$"):
        instance.structured(SEO, "Generate", {})
    assert time.monotonic() - started < 0.8
    assert stream.closed and stream.consumed < stream.count
    assert budget.calls == 1 and len(updates) == 2


def test_per_call_wall_deadline_interrupts_trickling_before_overall_budget(monkeypatch):
    monkeypatch.setattr("seo_content.providers.MAX_CALL_SECONDS", 0.08)
    stream = CountingStream(pause=0.01, chunk=b" ", count=1000)
    budget = Budget(max_seconds=10)
    instance = provider(monkeypatch, lambda _: httpx.Response(200, stream=stream), budget)
    with pytest.raises(ProviderError, match="^provider_timeout$"):
        instance._post("https://provider.test/", "test-only", {})
    assert stream.closed and budget.elapsed < 0.8 and budget.calls == 1


def test_final_allowed_call_can_complete(monkeypatch):
    instance = provider(
        monkeypatch, lambda _: httpx.Response(200, json={"ok": True}), Budget(max_calls=1)
    )
    assert instance._post("https://provider.test/", "test-only", {}) == {"ok": True}
    assert instance.budget.calls == 1


@pytest.mark.parametrize("fails", [False, True])
def test_deadline_restores_preexisting_handler_and_remaining_periodic_timer(monkeypatch, fails):
    from seo_content.providers import wall_deadline

    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)

    def previous_handler(_signum, _frame):
        raise AssertionError("The enclosing timer should not expire in this test")

    try:
        signal.signal(signal.SIGALRM, previous_handler)
        signal.setitimer(signal.ITIMER_REAL, 5, 2)
        started = time.monotonic()
        try:
            with wall_deadline(Budget(max_seconds=20)):
                time.sleep(0.01)
                if fails:
                    raise ProviderError("test_failure")
        except ProviderError:
            assert fails
        remaining, interval = signal.getitimer(signal.ITIMER_REAL)
        assert signal.getsignal(signal.SIGALRM) is previous_handler
        assert interval == 2
        assert remaining == pytest.approx(5 - (time.monotonic() - started), abs=0.02)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        signal.setitimer(signal.ITIMER_REAL, *old_timer)


def test_shorter_enclosing_alarm_is_delivered_without_being_postponed():
    from seo_content.providers import wall_deadline

    old_handler = signal.getsignal(signal.SIGALRM)
    old_timer = signal.getitimer(signal.ITIMER_REAL)
    delivered = []

    def previous_handler(_signum, _frame):
        delivered.append(time.monotonic())

    try:
        signal.signal(signal.SIGALRM, previous_handler)
        signal.setitimer(signal.ITIMER_REAL, 0.03)
        with wall_deadline(Budget(max_seconds=1)):
            time.sleep(0.07)
        assert len(delivered) == 1
        assert signal.getsignal(signal.SIGALRM) is previous_handler
        assert signal.getitimer(signal.ITIMER_REAL) == (0, 0)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        signal.setitimer(signal.ITIMER_REAL, *old_timer)
