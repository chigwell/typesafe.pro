"""Maintenance entrypoints must work even when generation adapters are absent."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = """
import importlib.abc
import json
import sys
from pathlib import Path

class BlockGeneration(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"langchain_core", "llmatch_messages"}:
            raise ModuleNotFoundError("generation adapters deliberately unavailable")

sys.meta_path.insert(0, BlockGeneration())
import httpx
from seo_content import __main__, maintenance
from seo_content.content_api import ContentApi

page = json.loads(Path(sys.argv[1]).read_text())["repairs"]["page"]
def respond(request):
    path = request.url.path
    if path.endswith("/drafts"):
        return httpx.Response(200, json={"items": [{"slug": page["slug"], "page": page}]})
    if path.endswith("/categories"):
        return httpx.Response(200, json={"items": []})
    if request.method == "PUT":
        return httpx.Response(200, json={"revision": 1})
    if path.endswith("/use-cases"):
        return httpx.Response(200, json={"total": 1, "items": [{"slug": page["slug"]}]})
    return httpx.Response(200, json={"page": page})

client = httpx.Client(transport=httpx.MockTransport(respond))
api = ContentApi(base="https://api.test", token="fixture-only", client=client)
maintenance.ContentApi = lambda: api
maintenance.httpx.Client = lambda **kwargs: client
sys.argv = ["seo_content", *sys.argv[2:]]
assert __main__.main() == 0
assert "seo_content.providers" not in sys.modules
assert "seo_content.review" not in sys.modules
assert "seo_content.pipeline" not in sys.modules
"""


@pytest.mark.parametrize("command", ["check", "import-files"])
def test_maintenance_commands_do_not_load_model_adapters(tmp_path, command):
    root = Path(__file__).parents[1]
    fixture = Path(__file__).parent / "fixtures" / "refactor-parity.json"
    args = [command]
    if command == "import-files":
        page = json.loads(fixture.read_text())["repairs"]["page"]
        (tmp_path / "manifest.json").write_text(json.dumps({"shards": [{"file": "pages.json"}]}))
        (tmp_path / "pages.json").write_text(json.dumps({"pages": [page]}))
        (tmp_path / "release.json").write_text(json.dumps({"pages": [{"slug": page["slug"]}]}))
        args += ["--content-dir", str(tmp_path), "--taxonomy", "heuristic"]
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(fixture), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(root)},
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_existing_exception_imports_keep_identical_types():
    from seo_content import content_api, errors, providers, review

    assert content_api.ContentApiError is errors.ContentApiError
    assert review.ReviewError is errors.ReviewError
    for name in ("ProviderError", "StageError", "BudgetExhausted"):
        assert getattr(providers, name) is getattr(errors, name)
    error = content_api.ContentApiError("failure", status=409, retryable=False)
    assert isinstance(error, providers.ProviderError)
    assert str(error) == "failure" and error.status == 409 and not error.retryable
    assert error.retry_after is None and error.detail is None
