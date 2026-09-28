import shutil

import pytest
from conftest import DEMO_CSS, DEMO_HTML, DEMO_JS, FakeProvider, concept, demo_code, idea
from pydantic import ValidationError

from seo_content.demo import build_demo, check_syntax, verify_demo
from seo_content.models import Demo, DemoCode, screen_demo_code
from seo_content.novelty import Rejected
from seo_content.pipeline import create_page, now, rebuild_demo


@pytest.mark.parametrize(
    "js",
    [
        "fetch('https://x')",
        "new XMLHttpRequest()",
        "new WebSocket('x')",
        "import('x')",
        "import x from 'y'",
        "eval('1')",
        "new Function('return 1')",
        "document.cookie",
        "localStorage.getItem('a')",
        "window.parent.document",
        "top.postMessage(1, '*')",
        "location.href = 'x'",
        "navigator.sendBeacon('x')",
        "open('https://x')",
        "document.write('<b>')",
        "</script><script>alert(1)</script>",
        "<!-- comment",
    ],
)
def test_screening_rejects_dangerous_script(js):
    with pytest.raises(ValueError):
        screen_demo_code("<p>ok</p>", "", js)


@pytest.mark.parametrize(
    "html",
    [
        "<script>1</script>",
        "<style>p{}</style>",
        "<img src=x>",
        "<iframe></iframe>",
        "<form></form>",
        "<a href='javascript:void(0)'>x</a>",
        "<link rel=stylesheet>",
        "<meta charset=utf-8>",
    ],
)
def test_screening_rejects_dangerous_markup(html):
    with pytest.raises(ValueError):
        screen_demo_code(html, "", "const a = 1;")


def test_screening_rejects_remote_css_but_allows_data_urls():
    with pytest.raises(ValueError):
        screen_demo_code("<p>", "p{background:url(https://x/y.png)}", "1")
    with pytest.raises(ValueError):
        screen_demo_code("<p>", "@import url(x.css);", "1")
    screen_demo_code("<p>", "p{background:url(data:image/png;base64,AAAA)}", "1")


def test_screening_allows_lookalike_identifiers():
    screen_demo_code(
        "<p>ok</p>",
        "",
        "const r = retrieval(1); myFunction(); el.style.top = '1px'; "
        "const p = node.parentElement; const opened = isOpen(); topScore = 2;"
        "button.addEventListener('click', function () { return 1; });"
        "const f = async function (x) { return x; }; function run() {}"
        "label.textContent = 'Enter a location'; const location_hint = item.location;"
        "dialog.open(); if (a == location_b) {}",
    )


@pytest.mark.parametrize(
    "js",
    [
        "window.location = 'x'",
        "location.href = 'x'",
        "location = 'x'",
        "document.location.assign('x')",
        "window.open('x')",
    ],
)
def test_screening_rejects_navigation(js):
    with pytest.raises(ValueError):
        screen_demo_code("<p>", "", js)


def test_demo_code_requires_distinct_samples():
    code = demo_code().model_dump()
    code["samples"][1]["state"] = code["samples"][0]["state"]
    with pytest.raises(ValidationError, match="distinct"):
        DemoCode.model_validate(code)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_check_syntax_rejects_broken_javascript():
    assert check_syntax("const a = 1;") is None
    with pytest.raises(Rejected, match="demo_syntax_error"):
        check_syntax("const a = ;")


def test_verify_demo_records_live_answers():
    demo = verify_demo(concept(), demo_code(), FakeProvider(), now)
    assert len(demo.samples) == 2
    assert demo.samples[0].request.questions == demo.questions
    assert demo.samples[0].response.answers["mood"].noul == 0.95
    assert demo.html == DEMO_HTML and demo.css == DEMO_CSS and demo.js == DEMO_JS


def test_verify_demo_rejects_failed_expectation():
    provider = FakeProvider()
    provider.example_probability = 0.3
    with pytest.raises(Rejected, match="demo_sample_failed"):
        verify_demo(concept(), demo_code(), provider, now)


def test_build_demo_retries_with_failure_as_feedback():
    class FlakySamples(FakeProvider):
        def evaluate(self, request):
            if self.demo_attempts == 1 and "mood" in request.questions:
                self.example_probability = 0.2
            else:
                self.example_probability = 0.95
            return super().evaluate(request)

    provider = FlakySamples()
    warnings = []
    demo = build_demo(idea(), concept(), provider, now, feedback=["Use blue"], warn=warnings.append)
    assert provider.demo_attempts == 2
    assert provider.demo_feedback[0] == "Use blue"
    assert "Previous attempt failed verification" in provider.demo_feedback[1]
    assert demo.samples[0].response.answers["mood"].noul == 0.95
    assert any("retrying" in item for item in warnings)


def test_build_demo_gives_up_after_three_attempts():
    provider = FakeProvider()
    provider.example_probability = 0.2
    with pytest.raises(Rejected, match="demo_sample_failed"):
        build_demo(idea(), concept(), provider, now)
    assert provider.demo_attempts == 3


def test_create_page_with_concept_carries_verified_demo(demo_page):
    assert demo_page.demo is not None
    assert demo_page.demo.title == "Mood bar 1"
    assert demo_page.demo.samples[0].verified_at.endswith("Z")


def test_rebuild_demo_keeps_prose_and_examples(demo_page):
    rebuilt = rebuild_demo(demo_page, concept(2), FakeProvider(), feedback=["Bigger bar"])
    assert rebuilt.intro == demo_page.intro
    assert rebuilt.examples == demo_page.examples
    assert rebuilt.demo.title == "Mood bar 2"
    assert rebuilt.updated_at >= demo_page.updated_at


def test_page_without_demo_still_valid():
    page = create_page(idea(), 0.95, FakeProvider())
    assert page.demo is None
    assert "demo" not in page.model_dump(exclude_none=True)


def test_demo_samples_must_use_demo_questions(demo_page):
    data = demo_page.demo.model_dump(exclude_none=True)
    data["questions"] = {"other": {"type": "noul", "instructions": "Other?"}}
    with pytest.raises(ValidationError, match="demo questions"):
        Demo.model_validate(data)


def test_screening_rejects_viewport_units():
    for css in ("#demo .x{min-height:60vh}", "#demo .x{width:100vw}", "#demo .x{height:50dvh}"):
        with pytest.raises(ValueError, match="viewport units"):
            screen_demo_code("<p>", css, "1")
    screen_demo_code("<p>", "#demo .x{height:100%;width:40px}", "const vh = 1;")


def test_demo_prompt_carries_the_brand_kit():
    from seo_content.demo import BRAND, brand_kit

    captured = {}

    class Capture(FakeProvider):
        def structured(self, schema, task, context, **options):
            if schema is DemoCode:
                captured.update(context)
                captured["task"] = task
            return super().structured(schema, task, context)

    verify_demo(concept(), demo_code(), FakeProvider(), now)
    from seo_content.demo import write_demo_code

    write_demo_code(idea(), concept(), Capture())
    kit = captured["brand_kit"]
    assert kit == brand_kit()
    assert {"ts-btn", "ts-input", "ts-chip", "ts-meter"} <= set(kit["classes"])
    assert "--ts-c1" in kit["tokens"] and BRAND["guidelines"] == kit["guidelines"]
    assert "brand_kit" in captured["task"]


def test_mispredicted_sample_is_dropped_when_two_remain():
    code = demo_code().model_dump()
    code["samples"].append(
        {
            "state": {"message": "It was fine, I guess."},
            "description": "An ambiguous middle case.",
            "expected": {"mood": {"type": "noul", "min": 0.9, "max": 1.0}},
        }
    )

    class MiddleIsLower(FakeProvider):
        def evaluate(self, request):
            ambiguous = request.state == {"message": "It was fine, I guess."}
            self.example_probability = 0.5 if ambiguous else 0.95
            return super().evaluate(request)

    demo = verify_demo(concept(), DemoCode.model_validate(code), MiddleIsLower(), now)
    assert [s.description for s in demo.samples] == [
        "A clearly positive message.",
        "Another positive message.",
    ]


def test_failure_message_carries_actual_answers():
    provider = FakeProvider()
    provider.example_probability = 0.3
    with pytest.raises(Rejected) as failure:
        verify_demo(concept(), demo_code(), provider, now)
    assert "the API returned {'mood': {'noul': 0.3}}" in str(failure.value)
