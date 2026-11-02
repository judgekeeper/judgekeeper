// Saves each LLM-as-a-judge grade for judgekeeper; run it from your project folder. Node.js only.
// It takes the arguments of judgekeeper.record() and writes the same line.
import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

type JkFields = { verdict?: unknown; score?: number; pass_mark?: number; reason?: string;
  judge?: string; rule?: string; name?: string; temperature?: number; id?: string | number;
  metadata?: Record<string, unknown> };

export function jkRecord(input: unknown, output: unknown, f: JkFields = {}): void {
  try {
    const name = f.name ?? "LLM-as-a-judge", now = new Date().toISOString();
    const meta: Record<string, unknown> = { ...(f.metadata ?? {}) };
    if (f.pass_mark != null && !("pass_mark" in meta)) meta.pass_mark = f.pass_mark;
    const said = typeof f.verdict === "string" ? f.verdict.trim().toLowerCase() : "";
    let label: unknown = f.verdict ?? null;
    if (typeof f.verdict === "boolean") label = f.verdict ? "pass" : "fail";
    else if (said === "pass" || said === "fail") label = said;
    else if (f.verdict == null && f.score != null && f.pass_mark != null)
      label = f.score >= f.pass_mark ? "pass" : "fail";
    const evaluator = Object.fromEntries(Object.entries(
      { model: f.judge, temperature: f.temperature, rule: f.rule }).filter(([, v]) => v != null));
    const line: Record<string, unknown> = { schema_version: 2,
      target_id: f.id == null ? null : String(f.id), name, annotator_kind: "LLM", label,
      score: f.score ?? null, explanation: f.reason == null ? null : String(f.reason), run: null,
      input, output, evaluator, created_at: now.slice(0, 19) + "Z" };
    if (Object.keys(meta).length) line.metadata = meta;
    const folder = join(".judgekeeper", "records");
    mkdirSync(folder, { recursive: true });
    const file = name.replace(/[^A-Za-z0-9._]+/g, "-").replace(/^[-.]+|[-.]+$/g, "")
      .slice(0, 60) || "LLM-as-a-judge";
    appendFileSync(join(folder, `${file}-${now.slice(0, 10)}-${process.pid}.jsonl`),
      JSON.stringify(line) + "\n");
  } catch { /* a record never stops your program */ }
}
