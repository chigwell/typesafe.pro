import type { CodeToken } from "@/lib/syntax";

/** Pure token markup; callers retain code containers and animation lifecycle. */
export function HighlightedCodeLines({
  lines,
  typing = false,
  contentKeys = false,
}: {
  lines: CodeToken[][];
  typing?: boolean;
  contentKeys?: boolean;
}) {
  return lines.map((line, lineIndex) => (
    <span className="code-line" key={contentKeys ? `${lineIndex}-${line.map((token) => token.text).join("")}` : lineIndex}>
      <span className="line-number" aria-hidden="true">{lineIndex + 1}</span>
      <span className="code-line-content">
        {line.map((token, tokenIndex) => (
          <span className={`token-${token.kind}`} key={contentKeys ? `${tokenIndex}-${token.text}` : tokenIndex}>{token.text}</span>
        ))}
        {typing && lineIndex === lines.length - 1 ? <span className="typing-cursor" aria-hidden="true" /> : null}
      </span>
    </span>
  ));
}
