import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

// Expand local imports in their source order for brand and cascade parity checks.
export function readStylesheet(path: string): string {
  return readFileSync(path, "utf8").replace(/^@import "([^"]+)";\n/gm, (_line, relative: string) =>
    readStylesheet(resolve(dirname(path), relative)),
  );
}
