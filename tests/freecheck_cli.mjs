// The browser's free check (website/assets/freecheck.js) on one file, as JSON on stdout:
// node tests/freecheck_cli.mjs PATH. The file's bytes are read as the page reads them (checkBytes).
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename } from "node:path";

const require = createRequire(import.meta.url);
const fc = require("../website/assets/freecheck.js");

const path = process.argv[2];
const result = fc.checkBytes(readFileSync(path), basename(path));
if (result.ok) {
  for (const judge of result.judges) {
    judge.lines = fc.reportLines(result, judge).map((line) => (line.k || "") + line.text);
  }
}
console.log(JSON.stringify(result));
