import { rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";

// Next's static exporter needs a parameter for an otherwise empty dynamic route.
// Its notFound() sentinel renders a 404 document; remove that document so the host
// returns an actual 404 for these unknown URLs rather than a 200 containing it.
for (const path of ["use-cases/_empty", "use-cases/page/0"]) {
  for (const extension of ["html", "txt"]) {
    await rm(fileURLToPath(new URL(`../out/${path}.${extension}`, import.meta.url)), { force: true });
  }
}
