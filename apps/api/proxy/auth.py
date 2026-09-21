import re
from secrets import compare_digest

from .config import TokenPair


def authenticate(
    headers: list[tuple[bytes, bytes]], pairs: tuple[TokenPair, ...]
) -> TokenPair | None:
    values = [value for name, value in headers if name.lower() == b"authorization"]
    if len(values) != 1:
        return None
    match = re.fullmatch(rb"(?i:Bearer) +([\x21-\x7e]+)", values[0])
    if match is None:
        return None
    candidate = match.group(1)
    matched = None
    for pair in pairs:
        if compare_digest(candidate, pair.client):
            matched = pair
    return matched
