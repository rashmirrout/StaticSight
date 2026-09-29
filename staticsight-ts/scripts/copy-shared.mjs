// Copies the shared tool contract and prompts next to the compiled server so the package is self-contained.
import { cpSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const shared = join(here, "..", "..", "shared");
const dest = join(here, "..", "dist", "_shared");
mkdirSync(join(dest, "prompts"), { recursive: true });
cpSync(join(shared, "tool-spec.json"), join(dest, "tool-spec.json"));
cpSync(join(shared, "prompts"), join(dest, "prompts"), { recursive: true });
cpSync(join(shared, "semantic"), join(dest, "semantic"), { recursive: true });
