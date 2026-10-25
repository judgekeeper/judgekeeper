# Example reports

One line per folder: what it is, the commit it ran on, the model and the date.

- **`coverage/`**: how often judgekeeper's ranges hold the true value, on simulated checks. Made by `scripts/coverage_check.py`; numbers from commit `a86ebfd`; no model; 2026-10-21.
- **`jailbreakbench/`**: judgekeeper's steps on JailbreakBench's judge-comparison set, checked against the experts' labels. Commit `6437d85` (first run `e3052c7`); GPT-4 (`openai:gpt-4-0613`), its grades taken from the dataset; 2026-10-21 (first run 2026-10-17).
- **`probes/`**: broken answers given to the two RAGTruth judges, to see what they do with them. Run on the judges only, not on judgekeeper's code; Claude Haiku 5.5 and Claude Sonnet 5.5; 2026-10-17.
- **`ragtruth/`**: two Claude judges on RAGTruth's news summaries, 3 runs each, with RAGTruth's human labels as the marks. Commit `7c77fd5`, measured again on `6437d85`; Claude Haiku 5.5 and Claude Sonnet 5.5; 2026-10-17.
- **`real-data-check/`**: judgekeeper's ranges on 5 real judges from 3 public datasets (LLMBar, MT-Bench, LLMJudge). Made by `scripts/real_data_check.py`; numbers from commit `6049ab7`; the judges' saved verdicts (Claude Haiku 4.5 on LLMBar, GPT-4 on MT-Bench, 3 LLMJudge runs), no new model call; 2026-10-16.
- **`records/`**: hand-written sample files in the records format, for the reference. Not a run; no model.
- **`site-example/`**: the project the website's home page shows, with made-up answers and marks. Commit `af1aad3`; judge named `openai:gpt-4.1-mini`, not called; 2026-10-24.
