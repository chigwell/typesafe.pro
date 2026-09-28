"""Scenario helpers shared by novelty checks and the content API client.

Pages live in the typesafe.pro content API (Postgres); this module no longer stores files.
"""

import hashlib
import json
import re

from .models import Idea, Page


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def compact(page: Page | Idea) -> dict:
    keys = Idea.model_fields.keys()
    return {key: getattr(page, key) for key in keys}


def normalized(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def fingerprint(page: Page | Idea) -> str:
    """Same scenario = same problem, input, decision and action (the API enforces uniqueness)."""
    return sha256(
        canonical(
            [
                normalized(getattr(page, key))
                for key in ("problem", "input_description", "decision", "action")
            ]
        )
    )
