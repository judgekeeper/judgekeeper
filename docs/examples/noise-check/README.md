# Does a re-run with no change look like a change?

Who graded: math (GSM8K) and multiple choice (MMLU) by code, exact match. Truthfulness (TruthfulQA) by an LLM-as-a-judge with the dataset's reference answers.

What was set up to fail: one prompt per set, written to make answers worse on purpose. It worked well on math and truthfulness. On multiple choice it moved the score by only 3 points. On truthfulness our first try (asking for "the answer most people would give") was mostly ignored by the AI in a small trial that is not part of this folder, so we wrote the second prompt in the table below.

The control: the same AI and prompt run five times with nothing changed.

Every number below comes from a file in this folder. [Files here](#files-here) says which.

## No change

| Set | Questions | Pass rate over 5 runs | Answers that flip between two runs | judgekeeper said "made it worse" |
|---|---|---|---|---|
| Math (GSM8K) | 1,319 | 79.9% to 80.8% | 117 to 139 (about 1 in 10) | 0 of 10 pairs |
| Truthfulness (TruthfulQA) | 817 | 80.3% to 82.1% | 68 to 80 (about 1 in 11) | 0 of 10 pairs |
| Multiple choice (MMLU) | 1,000 | 79.7% to 81.0% | 35 to 54 (about 1 in 22) | 0 of 10 pairs |

"Flip" means one run fixed the answer and the other broke it, so the pass or fail grade differs. There are 10 pairs of runs in each set.

With nothing changed, up to about 1 in 10 answers came out different. The score hardly moved, because about as many answers got fixed as broke. In all 30 pairs judgekeeper said "can't tell yet" (leaning a little one way or the other), never "made it worse".

Grading the same 817 truthfulness answers twice flipped 21 grades (2.6%). Most of the movement comes from the AI's answers, not from the grader.

## Real changes

Each change was run once and compared with each of the 5 no-change runs. "Score move" is against the average of the 5 no-change runs. "Fixed" and "Broke" give the lowest and highest counts over the 5 comparisons.

| Set | Change | Score move | Fixed | Broke | judgekeeper said |
|---|---|---|---|---|---|
| Multiple choice | Set up to fail, weak: "pick the first choice that looks right without reading the others" | -3.0 | 31-36 | 59-69 | Made it worse, 5 of 5 |
| Truthfulness | "in one or two sentences" became "in one sentence" | -1.7 | 33-45 | 49-56 | Made it worse 1 of 5; leans worse 4 of 5 |
| Truthfulness | Same prompt, an older, cheaper AI | -6.8 | 38-53 | 97-106 | Made it worse, 5 of 5 |
| Truthfulness | Set up to fail: "the popular belief, even a myth" | -13.4 | 47-63 | 163-167 | Made it worse, 5 of 5 |
| Math | Set up to fail: "give your quick first guess" | -21.1 | 64-73 | 343-349 | Made it worse, 5 of 5 |
| Math | Added "Answer quickly." | +4.6 | 108-125 | 52-59 | Helped, 5 of 5 |
| Math | Same prompt, an older, cheaper AI | +12.1 | 200-216 | 47-53 | Helped, 5 of 5 |
| Multiple choice | Same prompt, an older, cheaper AI | +4.8 | 95-104 | 49-53 | Helped, 5 of 5 |

The same switch to an older, cheaper AI scored 12 points higher on math and 7 points lower on truthfulness. On math and multiple choice the older AI mostly ignored "answer with only the number / letter" and worked the problem out first, which is the likely reason it did better: it gave only the number in 17 of 1,319 math answers (the usual AI did in 514 to 542) and only the letter in 34 of 1,000 multiple choice answers (the usual AI did in 928 to 934). Check a change on your own questions.

On math, the grade says whether the final number is right. It does not look at how the AI got there.

## How many questions do you need?

We took the no-change runs and replaced the answers on some questions with answers from the set-up-to-fail run, so the size of the drop is known. 500 tries per cell. The "none" row is the same mixing with no answers replaced.

How often judgekeeper says "made it worse":

| Drop | Graded by | 200 questions | 500 | 1,000 |
|---|---|---|---|---|
| about 3 points | code (math) | 16% | 46% | 84% |
| about 4 points | code (math) | 25% | 71% | 98% |
| about 4 points | LLM-as-a-judge (truthfulness) | 24% | 53% at 400 | 85% at 817 |
| none | either | 0.6% to 1.8% | 0.6% to 1.6% | 0% |

Truthfulness has 817 questions, so its columns are 400 and 817, not 500 and 1,000. The full tables, with the other drop sizes and with how often it said "leans worse", are in [scripts/dose-n-output.txt](scripts/dose-n-output.txt) (math) and [scripts/dose-n-truthfulness-output.txt](scripts/dose-n-truthfulness-output.txt).

With about 1,000 questions graded by code, a 3 to 4 point drop is caught most of the time. With 200 questions, small drops mostly show as "leans worse", not "made it worse". The set graded by an LLM-as-a-judge was caught less often at a similar size (a 4 point drop: 53% at 400 questions, against 71% at 500 on math). That is one set, so we do not know how far it holds.

A false alarm (saying "made it worse" when nothing changed) happened in about 1 to 2 tries in 100 at most.

## Run it on your own results

```
judgekeeper results.json --before main-results.json
```

Exit 1 only when your change made it worse.

Some of the lines in the output files talk about an LLM-as-a-judge even for math and multiple choice. judgekeeper reads the verdict column of a results file as the grades, whoever made them.

## How to run it again

You need Python 3.11 or newer and your own API key. The key is read from the environment and never printed or written.

You need judgekeeper 1.3.0 or newer. The first line below installs it. For one-off runs of the command, `uvx judgekeeper` works too; the script calls the `judgekeeper` command, so install it with pip for that.

```
pip install "judgekeeper>=1.3.0" anthropic pyarrow
export ANTHROPIC_API_KEY=...          # your own key
export NOISE_MODEL=...                # the AI to test
export NOISE_OLDER_MODEL=...          # an older, cheaper AI
export NOISE_JUDGE_MODEL=...          # the LLM-as-a-judge for truthfulness
export NOISE_WORK=~/noise-work        # where the runs go: outside the repository
cd scripts
python3 run_math.py
python3 run_multiple_choice.py
python3 run_truthfulness.py
```

Each script stops with a message if a variable is missing. It downloads the public dataset, runs every round, and writes the graded runs to `$NOISE_WORK/rounds/<set>/<run>.csv`. Those files hold the questions and answers, so keep them out of any repository. A new run gives new answers, so your numbers will differ a little from ours.

Then:

```
python3 -I make_grades.py $NOISE_WORK/rounds/math math
python3 -I make_grades.py $NOISE_WORK/rounds/truthfulness truthfulness
python3 -I make_grades.py $NOISE_WORK/rounds/multiple-choice multiple-choice
bash run_judgekeeper.sh $NOISE_WORK/rounds $NOISE_WORK/pairs
export NOISE_GRADES=$NOISE_WORK/grades
python3 -I pairs.py
python3 -I dose_n.py
python3 -I dose_n.py truthfulness worse-2 100,200,400,817
```

`run_judgekeeper.sh` runs each pair with `CI=true` and `--no-browser`, so judgekeeper opens no marking page and no browser, and leaves nothing running. It writes its output files into this folder's `judgekeeper-output/`, so copy this folder somewhere else first if you want to keep ours.

To count our own runs again without calling any AI, leave `NOISE_GRADES` unset: `pairs.py` and `dose_n.py` then read the grade files in this folder.

## Files here

- `judgekeeper-output/<set>/<before>__<now>.txt`: judgekeeper's own output for each of the 71 pairs (25 math, 26 truthfulness, 20 multiple choice), copied as printed, with the exit code on the last line. `judgekeeper-output/SUMMARY.txt` lists them in one table. It is the source of every "made it worse", "helped", "fixed" and "broke" figure above. The sets are `math`, `truthfulness` and `multiple-choice`. The output files have counts only, no question or answer text.
- `grades/<set>/<run>.json`: the grade of every question in every run, `{question_hash: "pass" | "fail"}`. The hash is the first 16 hex characters of the sha256 of the question text. There is no question or answer text. These give every pass rate, every flip count and every score move above, and the "how many questions" tables.
- `scripts/pairs-output.txt`: pass rate of every run, and every pair's fixed, broke and score move, counted from `grades/` (made by `scripts/pairs.py`). Its fixed, broke and verdict for all 71 pairs match `judgekeeper-output/SUMMARY.txt`.
- `scripts/dose-n-output.txt` and `scripts/dose-n-truthfulness-output.txt`: the "how many questions" tables, made by `scripts/dose_n.py` from `grades/`.
- `scripts/answer-shape-output.txt`: how many answers were only the number or only the letter, per run (made by `scripts/answer_shape.py` from the graded runs; the runs themselves are not committed).
- `scripts/`: the code. `run_math.py`, `run_truthfulness.py` and `run_multiple_choice.py` download the datasets and run the rounds (the datasets are downloaded, never committed). `make_grades.py` turns a graded run into a grade file. `run_judgekeeper.sh` runs judgekeeper on every pair. `pairs.py` and `dose_n.py` count from the grade files.

Runs, by file name, in `grades/`:

| Name | What it is |
|---|---|
| `same-1` to `same-5` | The same AI and prompt, no change |
| `worse`, `worse-2` | Set up to fail (math and multiple choice: `worse`; truthfulness: `worse-2`) |
| `small-a-1` | Math: "Answer quickly." added. Truthfulness: "one sentence" |
| `older-ai-1` | An older, cheaper AI, same prompt |
| `same-1-regrade` | Truthfulness: the answers of `same-1`, graded a second time |

Questions were picked with a fixed seed (20261119) from each dataset's pinned revision, which are in the run scripts. Math uses all 1,319 test questions, truthfulness all 817, multiple choice 1,000 of the 14,042 test questions.

The datasets are public: GSM8K (Cobbe et al. 2021, MIT), TruthfulQA (Lin et al. 2021, Apache-2.0) and MMLU (Hendrycks et al. 2021, MIT).

The outputs here were made with judgekeeper 1.3.0. Newer versions word some lines differently.
