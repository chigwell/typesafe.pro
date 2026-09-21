# typesafe.pro API

`api.typesafe.pro` is a simple HTTP endpoint for evaluating text and structured
application state with TypeSafe System One models. Send a state and typed questions;
receive structured answers with confidence and token usage.

The API is compatible with the TypeSafe evaluation endpoint. See the
[TypeSafe API reference](https://docs.typesafe.ai/api) for the full request and
response schema.

## Quick start

Call `POST https://api.typesafe.pro/v1/systemone` with JSON. Authentication is
optional: requests without a token use anonymous access. If you have an API token,
send it as a Bearer token to receive the limits for your account.

```sh
curl https://api.typesafe.pro/v1/systemone \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{
    "model": "jev-latest",
    "state": "The light is on.",
    "questions": {
      "is_on": {
        "type": "noul",
        "instructions": "Is the light on?"
      }
    }
  }'
```

Example response:

```json
{
  "model": "jev-1.13.0",
  "answers": {
    "is_on": {
      "type": "noul",
      "noul": 0.98
    }
  },
  "usage": {
    "input_tokens": 25,
    "output_tokens": 8
  }
}
```

The value returned for a `noul` answer is a probability from `0` to `1`.

## Authentication

Use a token in the `Authorization` header when one has been issued to you:

```sh
curl https://api.typesafe.pro/v1/systemone \
  --request POST \
  --header 'Authorization: Bearer YOUR_API_TOKEN' \
  --header 'Content-Type: application/json' \
  --data '{
    "model": "jev-latest",
    "state": {"ticket": "My payment has failed for three days."},
    "questions": {
      "is_urgent": {
        "type": "noul",
        "instructions": "Is this support request urgent?"
      }
    }
  }'
```

Missing, malformed, duplicate, or unknown tokens receive anonymous access. Do not
put a token in a URL, browser bundle, public repository, or client-side app.

## Ask typed questions

The `questions` object can combine several question types in one request.

```json
{
  "model": "jev-latest",
  "state": {
    "message": "I was charged twice and need help today.",
    "plan": "pro"
  },
  "questions": {
    "department": {
      "type": "choice",
      "instructions": "Which team should handle this request?",
      "criteria": {
        "billing": "Charges, invoices, refunds, or duplicate payments.",
        "technical": "Product bugs, outages, or integrations.",
        "sales": "Pricing, upgrades, or product information."
      }
    },
    "urgency": {
      "type": "score",
      "instructions": "How urgent is this request?",
      "criteria": ["Routine", "Soon", "Urgent"]
    },
    "needs_response_today": {
      "type": "noul",
      "instructions": "Does this request need a response today?"
    }
  }
}
```

`state` may be a string, JSON object, or JSON array. The response uses the same
keys you chose in `questions`.

## Limits and queueing

Each request can contain up to 64,000 context tokens and a body up to 10 MiB.
Requests are queued when shared upstream capacity is busy. A higher account tier
is served ahead of a lower tier; requests within the same tier stay FIFO.

| Access | Default rate | Queue deadline |
| --- | ---: | ---: |
| Anonymous | 30 requests/minute per IP | 3 seconds |
| Free token | 120 requests/minute per token | 10 seconds |
| Paid token | 1,000 requests/minute per token | 30 seconds |

Limits may change as the service evolves. `429` means the request rate limit or
queue deadline was reached. `503` means the queue or the shared limiter is full.
Both responses include `Retry-After`; wait at least that long and retry with
exponential backoff. Do not retry a non-idempotent request automatically unless
your application can safely handle duplicate work.

## Errors and request IDs

The API forwards successful and upstream validation responses as received. Its own
errors are JSON objects such as:

```json
{"error":"rate_limit_exceeded"}
```

Common statuses:

| Status | Meaning |
| --- | --- |
| `413` | Request body exceeds 10 MiB. |
| `429` | Rate limit reached or the request expired in the queue. |
| `502` | The upstream service could not be reached. |
| `503` | The local queue or admission service is unavailable. |
| `504` | The upstream request timed out. |

Every response includes `X-Request-ID`. You may provide your own value using 1-128
letters, digits, `_`, or `-`; otherwise the API generates one. Include this ID
when reporting a problem.

## Health check

```sh
curl --include https://api.typesafe.pro/health
```

The endpoint returns a small JSON status document and does not call the model.

## Privacy

Keep API tokens server-side. The service retains operational activity and error
events for seven days, including real client IP addresses for abuse investigation
and usage statistics. Client token identifiers are hashed. Error records omit
authorization values and request bodies and keep only a bounded, sanitized portion
of an upstream error response. These records are available only through the
authenticated admin API.

## Operations dashboard

The read-only dashboard at `/admin` uses the protected `/admin/api` routes on the
API host. See [admin operations](docs/admin.md) for configuration, secrets,
retention, and local verification.

## Support

For full model behavior, question types, and response shapes, use the
[TypeSafe API reference](https://docs.typesafe.ai/api). When contacting support,
include the `X-Request-ID`, approximate time of the request, and the HTTP status.
