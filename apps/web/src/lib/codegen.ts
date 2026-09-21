import { API_BASE } from "./playground";
import { API_ENDPOINT, type EvaluationRequest } from "./typesafe";

export type LanguageId = "python" | "javascript" | "typescript" | "curl" | "go" | "php" | "java";

export const LANGUAGES: Record<LanguageId, { label: string; filename: string; comment: string }> = {
  python: { label: "Python", filename: "example.py · Python 3", comment: "#" },
  javascript: { label: "JavaScript", filename: "example.mjs · JavaScript", comment: "//" },
  typescript: { label: "TypeScript", filename: "example.ts · TypeScript", comment: "//" },
  curl: { label: "cURL", filename: "Terminal · cURL", comment: "#" },
  go: { label: "Go", filename: "main.go · Go", comment: "//" },
  php: { label: "PHP", filename: "example.php · PHP + cURL", comment: "//" },
  java: { label: "Java", filename: "Example.java · Java 17+", comment: "//" },
};

export const LANGUAGE_ORDER = Object.keys(LANGUAGES) as LanguageId[];

function pythonLiteral(value: unknown, depth = 0): string {
  if (value === null) return "None";
  if (typeof value === "boolean") return value ? "True" : "False";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "number") return String(value);
  const pad = "    ".repeat(depth);
  if (Array.isArray(value)) {
    if (!value.length) return "[]";
    return `[\n${value.map((item) => `${pad}    ${pythonLiteral(item, depth + 1)},`).join("\n")}\n${pad}]`;
  }
  if (typeof value === "object" && value) {
    const entries = Object.entries(value);
    if (!entries.length) return "{}";
    return `{\n${entries
      .map(([key, item]) => `${pad}    ${JSON.stringify(key)}: ${pythonLiteral(item, depth + 1)},`)
      .join("\n")}\n${pad}}`;
  }
  return JSON.stringify(value);
}

function javascriptLiteral(value: unknown, depth = 0): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  const pad = "  ".repeat(depth);
  if (Array.isArray(value)) {
    if (!value.length) return "[]";
    return `[\n${value.map((item) => `${pad}  ${javascriptLiteral(item, depth + 1)}`).join(",\n")}\n${pad}]`;
  }
  const entries = Object.entries(value);
  if (!entries.length) return "{}";
  return `{\n${entries
    .map(([key, item]) => {
      const safeKey = key === "__proto__" ? '["__proto__"]' : JSON.stringify(key);
      return `${pad}  ${safeKey}: ${javascriptLiteral(item, depth + 1)}`;
    })
    .join(",\n")}\n${pad}}`;
}

export function makeCode(language: LanguageId, payload: EvaluationRequest): string {
  const json = JSON.stringify(payload, null, 2);
  const endpoint = `${API_BASE}${API_ENDPOINT}`;
  const jsPayload = javascriptLiteral(payload);

  if (language === "python") {
    return `import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE_URL = "${API_BASE}"
payload = ${pythonLiteral(payload)}

request = Request(
    f"{BASE_URL}${API_ENDPOINT}",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

try:
    with urlopen(request, timeout=20) as response:
        result = json.load(response)
except HTTPError as error:
    raise SystemExit(f"API returned HTTP {error.code}") from error
except URLError as error:
    raise SystemExit(f"Connection failed: {error.reason}") from error

print(json.dumps(result["answers"], indent=2))
`;
  }

  if (language === "javascript" || language === "typescript") {
    const typeCheck =
      language === "typescript"
        ? `const result: unknown = await response.json();
if (typeof result !== "object" || result === null || !("answers" in result)) {
  throw new Error("Invalid API response");
}
console.log(result.answers);

export {};
`
        : `const result = await response.json();
console.log(result.answers);
`;
    return `const BASE_URL = "${API_BASE}";
const payload = ${jsPayload};

const response = await fetch(
  \`\${BASE_URL}${API_ENDPOINT}\`,
  {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "omit",
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(20_000),
  },
);

if (!response.ok) {
  throw new Error(\`API returned HTTP \${response.status}\`);
}
${typeCheck}`;
  }

  if (language === "curl") {
    return `curl --silent --show-error --fail-with-body \\
  --max-time 20 \\
  --request POST '${endpoint}' \\
  --header 'Content-Type: application/json' \\
  --data-binary @- <<'TYPESAFE_REQUEST_JSON'
${json}
TYPESAFE_REQUEST_JSON
`;
  }

  if (language === "go") {
    const bodyLiteral = json.includes("`") ? JSON.stringify(json) : `\`${json}\``;
    return `package main

import (
    "bytes"
    "fmt"
    "io"
    "net/http"
    "os"
    "time"
)

func run() error {
    body := []byte(${bodyLiteral})
    req, err := http.NewRequest(
        http.MethodPost, "${endpoint}", bytes.NewReader(body),
    )
    if err != nil { return err }
    req.Header.Set("Content-Type", "application/json")
    client := &http.Client{Timeout: 20 * time.Second}
    res, err := client.Do(req)
    if err != nil { return err }
    defer res.Body.Close()
    if res.StatusCode < 200 || res.StatusCode >= 300 {
        return fmt.Errorf("API returned HTTP %d", res.StatusCode)
    }
    data, err := io.ReadAll(io.LimitReader(res.Body, (1<<20)+1))
    if err != nil { return err }
    if len(data) > 1<<20 {
        return fmt.Errorf("response exceeds 1 MiB")
    }
    fmt.Println(string(data))
    return nil
}

func main() {
    if err := run(); err != nil {
        fmt.Fprintln(os.Stderr, err)
        os.Exit(1)
    }
}
`;
  }

  if (language === "php") {
    return `<?php
declare(strict_types=1);

$body = <<<'TYPESAFE_REQUEST_JSON'
${json}
TYPESAFE_REQUEST_JSON;

$client = curl_init('${endpoint}');
if ($client === false) {
    throw new RuntimeException('Could not initialise cURL');
}
curl_setopt_array($client, [
    CURLOPT_POST => true,
    CURLOPT_POSTFIELDS => $body,
    CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_CONNECTTIMEOUT => 10,
    CURLOPT_TIMEOUT => 20,
]);

$response = curl_exec($client);
$status = curl_getinfo($client, CURLINFO_RESPONSE_CODE);
$error = curl_error($client);
curl_close($client);

if ($response === false) {
    throw new RuntimeException($error);
}
if ($status < 200 || $status >= 300) {
    throw new RuntimeException("API returned HTTP $status");
}
$result = json_decode($response, true, 512, JSON_THROW_ON_ERROR);
echo json_encode($result['answers'], JSON_PRETTY_PRINT | JSON_THROW_ON_ERROR), PHP_EOL;
`;
  }

  const lines = json.split("\n").map((line) => `            ${JSON.stringify(`${line}\n`)}`).join(" +\n");
  return `import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

public class Example {
    public static void main(String[] args) throws Exception {
        String body =
${lines};

        HttpClient client = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create("${endpoint}"))
            .timeout(Duration.ofSeconds(20))
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(body))
            .build();
        HttpResponse<String> response = client.send(
            request, HttpResponse.BodyHandlers.ofString()
        );
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IllegalStateException(
                "API returned HTTP " + response.statusCode()
            );
        }
        System.out.println(response.body());
    }
}
`;
}

