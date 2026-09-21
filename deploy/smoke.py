"""Check health and optionally anonymous, invalid-token and legacy-token access."""

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--env-file")
    args = parser.parse_args()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(path, data=None, token=None):
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "typesafe-proxy-deploy/1.0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            args.base_url + path, data=data, headers=headers
        )
        try:
            with opener.open(request, timeout=125) as result:
                if not result.headers.get("X-Request-ID"):
                    raise RuntimeError("Missing X-Request-ID")
                return result.status, result.read()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read()

    status, raw = call("/health")
    if status != 200:
        raise RuntimeError(f"Health check returned HTTP {status}")
    health = json.loads(raw)
    if (
        status != 200
        or health.get("service") != "typesafe-proxy"
        or health.get("release") != args.release
    ):
        raise RuntimeError("Health check or release mismatch")
    if args.env_file:
        env = dict(
            line.split("=", 1) for line in Path(args.env_file).read_text().splitlines()
        )
        payload = {
            "model": "jev-latest",
            "state": "The light is on.",
            "questions": {
                "is_on": {"type": "noul", "instructions": "Is the light on?"}
            },
        }
        tokens = [None, "invalid-smoke-test-key"]
        if env.get("TYPESAFE_TEST_API_TOKEN_1"):
            tokens.append(env["TYPESAFE_TEST_API_TOKEN_1"])
        for token in tokens:
            status, raw = call("/v1/systemone", json.dumps(payload).encode(), token)
            if status != 200:
                raise RuntimeError(f"Live upstream check returned HTTP {status}")
            result = json.loads(raw)
            if (
                not {"model", "answers", "usage"} <= result.keys()
                or "is_on" not in result["answers"]
            ):
                raise RuntimeError(
                    "Live upstream response does not match the TypeSafe contract"
                )
        print("Live anonymous, invalid-token and configured legacy-token checks: OK")
    print(f"Health and release checks: OK ({args.release})")


if __name__ == "__main__":
    try:
        main()
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
    ) as error:
        # Never print response bodies, request URLs or exception details from HTTP libraries.
        if isinstance(error, RuntimeError):
            print(str(error))
        else:
            print(f"Smoke check failed ({type(error).__name__})")
        raise SystemExit(1) from None
