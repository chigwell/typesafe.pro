import type { LanguageId } from "./codegen";

export type TokenKind = "plain" | "keyword" | "string" | "comment" | "number" | "flag";

export type CodeToken = {
  kind: TokenKind;
  text: string;
};

const KEYWORDS: Record<LanguageId, Set<string>> = {
  python: new Set([
    "as",
    "except",
    "False",
    "from",
    "import",
    "None",
    "print",
    "raise",
    "SystemExit",
    "try",
    "True",
    "with",
  ]),
  javascript: new Set([
    "AbortSignal",
    "await",
    "const",
    "console",
    "credentials",
    "fetch",
    "if",
    "JSON",
    "method",
    "new",
    "null",
    "throw",
    "true",
  ]),
  typescript: new Set([
    "AbortSignal",
    "await",
    "const",
    "console",
    "credentials",
    "Error",
    "export",
    "fetch",
    "if",
    "JSON",
    "method",
    "new",
    "null",
    "object",
    "throw",
    "true",
    "typeof",
    "unknown",
  ]),
  curl: new Set(["curl", "POST", "TYPESAFE_REQUEST_JSON"]),
  go: new Set([
    "bytes",
    "defer",
    "err",
    "fmt",
    "func",
    "if",
    "import",
    "io",
    "main",
    "net",
    "nil",
    "os",
    "package",
    "return",
    "time",
  ]),
  php: new Set([
    "array",
    "curl_close",
    "curl_exec",
    "curl_getinfo",
    "curl_init",
    "curl_setopt_array",
    "declare",
    "echo",
    "false",
    "if",
    "JSON_THROW_ON_ERROR",
    "RuntimeException",
    "strict_types",
    "throw",
    "true",
  ]),
  java: new Set([
    "class",
    "Duration",
    "Exception",
    "HttpClient",
    "HttpRequest",
    "HttpResponse",
    "if",
    "import",
    "new",
    "public",
    "static",
    "String",
    "throw",
    "throws",
    "void",
  ]),
};

const TOKEN_PATTERN =
  /("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\/\/.*$|#.*$|--[a-z-]+|\b\d[\d_]*(?:\.\d+)?\b|\b[A-Za-z_][A-Za-z0-9_]*\b)/g;

export function highlightCode(text: string, language: LanguageId): CodeToken[][] {
  return text.replace(/\n$/, "").split("\n").map((line) => highlightLine(line, language));
}

function highlightLine(line: string, language: LanguageId): CodeToken[] {
  const tokens: CodeToken[] = [];
  let offset = 0;

  for (const match of line.matchAll(TOKEN_PATTERN)) {
    const index = match.index ?? 0;
    if (index > offset) {
      tokens.push({ kind: "plain", text: line.slice(offset, index) });
    }
    const text = match[0];
    tokens.push({ kind: classify(text, language), text });
    offset = index + text.length;
  }

  if (offset < line.length) {
    tokens.push({ kind: "plain", text: line.slice(offset) });
  }
  return tokens.length ? tokens : [{ kind: "plain", text: "" }];
}

function classify(text: string, language: LanguageId): TokenKind {
  if (text.startsWith("//") || text.startsWith("#")) return "comment";
  if (text.startsWith("--")) return "flag";
  if (text.startsWith('"') || text.startsWith("'") || text.startsWith("`")) return "string";
  if (/^\d/.test(text)) return "number";
  return KEYWORDS[language].has(text) ? "keyword" : "plain";
}

