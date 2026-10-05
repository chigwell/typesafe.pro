import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import { readStylesheet } from "@/test/styles";

it("preserves the pre-extraction stylesheet bytes and cascade order", () => {
  // Intentional design changes should update this digest after reviewing visual parity.
  const source = readStylesheet(resolve(__dirname, "globals.css"));
  expect(createHash("sha256").update(source).digest("hex")).toBe("5fc51204171b3d175809a69cae12df1423deb70b46ba2f72c7cc5f18e0c83c40");
});
