import json
import math
import zlib

CAPTURE_BYTES = 64 * 1024


def estimate_tokens(body: bytes) -> int:
    # An intentionally conservative byte estimate for metrics, not a tokenizer guarantee.
    return len(body) + 1024


def inspect_response(raw, encoding, truncated):
    if truncated:
        return None, None, None
    try:
        if encoding in ("gzip", "deflate"):
            decoder = zlib.decompressobj(31 if encoding == "gzip" else 15)
            raw = decoder.decompress(raw, CAPTURE_BYTES + 1)
            if len(raw) > CAPTURE_BYTES or not decoder.eof:
                return None, None, None
        elif encoding and encoding != "identity":
            return None, None, None
        data = json.loads(raw)
        return data, raw.decode("utf-8", "replace"), None
    except (ValueError, zlib.error, RecursionError) as error:
        return None, raw.decode("utf-8", "replace"), type(error).__name__


def usage_tokens(data):
    if not isinstance(data, dict) or not isinstance(data.get("usage"), dict):
        return None
    usage = data["usage"]
    values = [usage.get("input_tokens"), usage.get("output_tokens")]
    if all(type(value) is int and 0 <= value <= 1_000_000_000 for value in values):
        return sum(values)
    return None


def valid_response(data, questions):
    return (
        isinstance(data, dict)
        and isinstance(data.get("model"), str)
        and isinstance(data.get("answers"), dict)
        and (questions is None or set(data["answers"]) == questions)
        and usage_tokens(data) is not None
        and all(valid_answer(answer) for answer in data["answers"].values())
    )


def finite_number(value):
    return type(value) is int or (type(value) is float and math.isfinite(value))


def probability(value):
    return finite_number(value) and 0 <= value <= 1


def valid_answer(answer):
    if not isinstance(answer, dict):
        return False
    kind = answer.get("type")
    if kind == "noul":
        return probability(answer.get("noul"))
    if kind not in ("choice", "score") or not probability(answer.get("confidence")):
        return False
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict) or not probabilities:
        return False
    if not all(probability(value) for value in probabilities.values()):
        return False
    if kind == "choice":
        return isinstance(answer.get("choice"), str) and answer["choice"] in probabilities
    return finite_number(answer.get("score")) and isinstance(answer.get("legend"), dict)
