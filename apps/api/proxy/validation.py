"""Local checks for the public evaluation contract; never rewrite request bytes."""

import json
import math


class InvalidRequest(Exception):
    def __init__(self, code, status, *, path=None, reason=None, allow=None):
        super().__init__(code)
        self.code, self.status = code, status
        self.details = {"path": path, "reason": reason} if path is not None else None
        self.allow = allow


def validate_route(scope):
    if scope["path"] == "/health":
        raise InvalidRequest("method_not_allowed", 405, allow="GET")
    if scope["path"] != "/v1/systemone":
        raise InvalidRequest("endpoint_not_found", 404)
    if scope["method"] != "POST":
        raise InvalidRequest("method_not_allowed", 405, allow="POST, OPTIONS")


def validate_media(headers):
    types = [v for k, v in headers if k.lower() == b"content-type"]
    encodings = [v for k, v in headers if k.lower() == b"content-encoding"]
    if (
        len(types) != 1
        or types[0].split(b";", 1)[0].strip().lower() != b"application/json"
        or (encodings and (len(encodings) != 1 or encodings[0].strip().lower() != b"identity"))
    ):
        raise InvalidRequest("unsupported_media_type", 415)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("Non-finite number")


def _float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite number")
    return result


def validate_body(body):
    try:
        data = json.loads(
            body, object_pairs_hook=_object, parse_constant=_constant, parse_float=_float
        )
    except (ValueError, RecursionError):
        raise InvalidRequest("invalid_json", 400) from None

    def require(condition, path, reason):
        if not condition:
            raise InvalidRequest("invalid_request", 422, path=path, reason=reason)

    structured = (str, dict, list)
    require(isinstance(data, dict), [], "Expected an object")
    require(isinstance(data.get("model"), str), ["model"], "Expected a string")
    require(
        isinstance(data.get("state"), structured), ["state"], "Expected string, object or array"
    )
    questions = data.get("questions")
    require(isinstance(questions, dict), ["questions"], "Expected an object")
    for name, question in questions.items():
        path = ["questions", name]
        require(isinstance(question, dict), path, "Expected an object")
        kind = question.get("type")
        require(
            kind in ("noul", "choice", "score"), path + ["type"], "Expected noul, choice or score"
        )
        require(
            isinstance(question.get("instructions"), structured),
            path + ["instructions"],
            "Expected string, object or array",
        )
        criteria = question.get("criteria")
        path += ["criteria"]
        if kind == "noul" and "criteria" in question:
            require(isinstance(criteria, dict), path, "Expected an object")
            for key in ("true", "false"):
                if key in criteria:
                    require(
                        isinstance(criteria[key], structured),
                        path + [key],
                        "Expected string, object or array",
                    )
        elif kind == "choice":
            require(isinstance(criteria, dict), path, "Expected an object")
            require(1 <= len(criteria) <= 255, path, "Expected 1 to 255 options")
            for key, value in criteria.items():
                require(
                    value is None or isinstance(value, structured),
                    path + [key],
                    "Expected string, object, array or null",
                )
        elif kind == "score":
            require(isinstance(criteria, list), path, "Expected an array")
            require(2 <= len(criteria) <= 10, path, "Expected 2 to 10 levels")
            for index, value in enumerate(criteria):
                require(
                    isinstance(value, structured),
                    path + [index],
                    "Expected string, object or array",
                )
