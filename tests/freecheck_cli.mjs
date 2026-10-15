// The browser's free check (website/assets/freecheck.js) on one file, as JSON on stdout:
// node tests/freecheck_cli.mjs PATH. The file is decoded as the page decodes it (UTF-8, fatal).
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename } from "node:path";

const require = createRequire(import.meta.url);
const fc = require("../website/assets/freecheck.js");

const path = process.argv[2];
let text;
try {
  text = new TextDecoder("utf-8", { fatal: true }).decode(readFileSync(path));
} catch {
  console.log(JSON.stringify({ ok: false, kind: "not-utf8", message: fc.NOT_UTF8 }));
  process.exit(0);
}
const result = fc.check(text, basename(path));
if (result.ok) {
  for (const judge of result.judges) {
    judge.lines = fc.reportLines(result, judge).map((line) => (line.k || "") + line.text);
  }
}
console.log(JSON.stringify(result));
