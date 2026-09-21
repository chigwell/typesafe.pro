import { describe, expect, it } from "vitest";
import { highlightCode } from "./syntax";

describe("highlightCode", () => {
  it("classifies language-specific keywords, strings, comments, and numbers", () => {
    const lines = highlightCode('const name = "Jev"; // 20 seconds', "typescript");
    const tokens = lines[0];

    expect(tokens).toContainEqual({ kind: "keyword", text: "const" });
    expect(tokens).toContainEqual({ kind: "string", text: '"Jev"' });
    expect(tokens).toContainEqual({ kind: "comment", text: "// 20 seconds" });
  });

  it("classifies cURL flags", () => {
    const lines = highlightCode("curl --request POST", "curl");

    expect(lines[0]).toContainEqual({ kind: "flag", text: "--request" });
    expect(lines[0]).toContainEqual({ kind: "keyword", text: "POST" });
  });
});

