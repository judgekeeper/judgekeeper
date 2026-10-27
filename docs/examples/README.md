# Example reports

One line per folder: what it is, the commit it ran on, the model and the date.

- **`coverage/`**: how often judgekeeper's ranges hold the true value, on simulated checks. Made by `scripts/coverage_check.py`; numbers from commit `a86ebfd`, run again on `bc0d099` with the same numbers; no model; 2026-10-21 (again 2026-10-25).
- **`jailbreakbench/`**: judgekeeper's steps on JailbreakBench's judge-comparison set, checked against the experts' labels. 100 draws of 100 marks on commit `7ec7a5e`, two batches (250 marks per draw) on `bc0d099`, one round on `6437d85` (first run `e3052c7`); GPT-4 (`openai:gpt-4-0613`), its grades taken from the dataset; 2026-10-27 (two batches 2026-10-25, one round 2026-10-21, first run 2026-10-17).
- **`kept-aside/`**: what `fix` says on simulated new rules whose true effect is known, through its own split and verdict. Made by `scripts/kept_aside_check.py`; numbers from commit `461272c`; no model; 2026-10-27.
- **`probes/`**: broken answers given to the two RAGTruth judges, to see what they do with them. Run on the judges only, with the RAGTruth runs from commit `bc0d099`; Claude Haiku 5.5 and Claude Sonnet 5.5; 2026-10-25.
- **`ragtruth/`**: two Claude judges on RAGTruth's news summaries, 3 runs each, with RAGTruth's human labels as the marks. Commit `bc0d099`; Claude Haiku 5.5 and Claude Sonnet 5.5; 2026-10-25.
- **`real-data-check/`**: judgekeeper's ranges on 5 real judges from 3 public datasets (LLMBar, MT-Bench, LLMJudge). Made by `scripts/real_data_check.py`; numbers from commit `6049ab7`; the judges' saved verdicts (Claude Haiku 4.5 on LLMBar, GPT-4 on MT-Bench, 3 LLMJudge runs), no new model call; 2026-10-16.
- **`records/`**: hand-written sample files in the records format, for the reference. Not a run; no model.
- **`site-example/`**: the project the website's home page shows, with made-up answers and marks. Commit `af1aad3`; judge named `openai:gpt-4.1-mini`, not called; 2026-10-24.

Note: judgekeeper only reads files and makes no AI call. In `ragtruth/` and `probes/`, promptfoo asked the models. The parts of `coverage/` about asking an LLM-as-a-judge again simulate a re-check that judgekeeper no longer makes.
