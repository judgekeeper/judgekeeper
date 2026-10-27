# What `fix` says on made-up new rules

Written by `scripts/kept_aside_check.py`; do not edit by hand.

`judgekeeper fix` keeps half of each group of marks aside (rounded up, at least 5 Pass and 5 Fail) and tests a new rule on those only. Here, made-up cases go through judgekeeper's own split and its own verdict, with new rules whose true effect is known. How many marks a clear answer needs depends on how much better or worse the new rule is: small improvements need many more marks. 20,000 made-up cases per row, seed 20261027, commit `461272c`. No AI call.

## The result

A new rule that fixes almost all of the LLM-as-a-judge's mistakes (9 in 10) and breaks 2 in 100 of its right answers gets a clear answer (not "can't tell yet") most of the time from 50 marks; one that fixes a quarter needs 80; one that fixes 1 in 10 and breaks 5 in 100 needs more than 120. With 80 marks, the quarter rule reads "safe to try" in 58.5 to 83.0 cases in 100 and "better" in 0.0 to 4.6. A large fix of a clearly wrong rule (one that fixes about 9 in 10 of the mistakes of an LLM-as-a-judge agreeing 70% of the time, and breaks about 2 in 100 right answers) reads "better" in 95.2 cases in 100 with 80 marks, and "safe to try" in 4.8. A rule that is truly the same or worse is called "better" in at most 0.1 cases in 100, and one that is truly the same or better is called "worse" in at most 0.2: rare but not zero, and only for rules within 6.0 points of no change. A worse rule can still slip through: one that fixes nothing and breaks 1 in 10 right answers is caught ("worse") in only 24.8 to 46.7 cases in 100 with 120 marks, and reads "safe to try" (not more than 10 points worse) in 2.1 to 7.0.

## Marks for a clear answer

The fewest marks tried (30, 50, 80, 120) at which `fix` gives a clear answer most of the time, whether the LLM-as-a-judge agrees with the person 70%, 80% or 90% of the time, and there how often it says each, in 100 cases (low to high over the agreements). New rule: of the answers kept aside, the share of the LLM-as-a-judge's mistakes it fixes and the share of its right answers it breaks.

| New rule | Marks | Better | Safe to try | Can't tell yet | Worse |
|---|---|---|---|---|---|
| fixes 10%, breaks 0% | 80 | 0.0 to 0.1 | 99.9 to 100.0 | 0.0 | 0.0 |
| fixes 10%, breaks 2% | 80 | 0.0 to 0.1 | 50.7 to 67.9 | 32.0 to 49.3 | 0.0 |
| fixes 10%, breaks 5% | more than 120 | | | | |
| fixes 25%, breaks 0% | 80 | 0.0 to 7.5 | 92.5 to 100.0 | 0.0 | 0.0 |
| fixes 25%, breaks 2% | 80 | 0.0 to 4.6 | 58.5 to 83.0 | 12.5 to 41.4 | 0.0 |
| fixes 25%, breaks 5% | 120 | 0.0 to 6.0 | 49.3 to 81.2 | 12.7 to 49.5 | 0.0 to 1.2 |
| fixes 50%, breaks 0% | 50 | 0.0 to 18.0 | 74.4 to 93.3 | 0.8 to 25.6 | 0.0 |
| fixes 50%, breaks 2% | 50 | 0.0 to 13.2 | 50.9 to 77.9 | 8.9 to 49.0 | 0.0 |
| fixes 50%, breaks 5% | 120 | 0.6 to 46.3 | 52.3 to 78.0 | 1.4 to 33.8 | 0.0 to 0.2 |
| fixes 90%, breaks 0% | 50 | 1.0 to 84.2 | 15.8 to 89.6 | 0.0 to 9.4 | 0.0 |
| fixes 90%, breaks 2% | 50 | 0.8 to 69.4 | 29.9 to 70.1 | 0.7 to 30.9 | 0.0 |
| fixes 90%, breaks 5% | 80 | 2.6 to 81.9 | 17.7 to 62.6 | 0.4 to 34.8 | 0.0 |
| fixes 0%, breaks 10% | more than 120 | | | | |
| fixes 0%, breaks 25% | 80 | 0.0 | 0.0 | 8.3 to 25.8 | 74.1 to 91.7 |
| no real change | 120 | 0.0 to 0.1 | 72.7 to 92.7 | 7.3 to 27.0 | 0.0 to 0.1 |

## How often `fix` says each, in 100 cases

True change: the points of agreement with the person the new rule really gains or loses. Agrees: how often the LLM-as-a-judge agrees with the person. Kept aside: the marks kept aside, on average.

| Marks | Agrees | New rule | True change | Kept aside | Better | Safe to try | Can't tell yet | Worse |
|---|---|---|---|---|---|---|---|---|
| 30 | 70% | fixes 10%, breaks 0% | +3.0 | 16 | 0.0 | 8.4 | 91.6 | 0.0 |
| 30 | 70% | fixes 10%, breaks 2% | +1.6 | 16 | 0.0 | 6.9 | 93.1 | 0.0 |
| 30 | 70% | fixes 10%, breaks 5% | -0.5 | 16 | 0.0 | 4.6 | 95.4 | 0.0 |
| 30 | 70% | fixes 25%, breaks 0% | +7.5 | 16 | 0.0 | 35.4 | 64.6 | 0.0 |
| 30 | 70% | fixes 25%, breaks 2% | +6.1 | 16 | 0.0 | 28.8 | 71.2 | 0.0 |
| 30 | 70% | fixes 25%, breaks 5% | +4.0 | 16 | 0.0 | 20.8 | 79.2 | 0.0 |
| 30 | 70% | fixes 50%, breaks 0% | +15.0 | 16 | 1.5 | 74.4 | 24.0 | 0.0 |
| 30 | 70% | fixes 50%, breaks 2% | +13.6 | 16 | 1.2 | 61.0 | 37.7 | 0.0 |
| 30 | 70% | fixes 50%, breaks 5% | +11.5 | 16 | 0.8 | 45.5 | 53.7 | 0.0 |
| 30 | 70% | fixes 90%, breaks 0% | +27.0 | 16 | 22.9 | 75.4 | 1.7 | 0.0 |
| 30 | 70% | fixes 90%, breaks 2% | +25.6 | 16 | 18.3 | 68.5 | 13.2 | 0.0 |
| 30 | 70% | fixes 90%, breaks 5% | +23.5 | 16 | 14.2 | 58.0 | 27.8 | 0.0 |
| 30 | 70% | fixes 0%, breaks 10% | -7.0 | 16 | 0.0 | 0.0 | 100.0 | 0.0 |
| 30 | 70% | fixes 0%, breaks 25% | -17.5 | 16 | 0.0 | 0.0 | 96.2 | 3.8 |
| 30 | 70% | no real change | -0.0 | 16 | 0.0 | 5.2 | 94.8 | 0.0 |
| 50 | 70% | fixes 10%, breaks 0% | +3.0 | 26 | 0.0 | 56.3 | 43.7 | 0.0 |
| 50 | 70% | fixes 10%, breaks 2% | +1.6 | 26 | 0.0 | 40.7 | 59.3 | 0.0 |
| 50 | 70% | fixes 10%, breaks 5% | -0.5 | 26 | 0.0 | 24.2 | 75.8 | 0.0 |
| 50 | 70% | fixes 25%, breaks 0% | +7.5 | 26 | 0.8 | 87.5 | 11.6 | 0.0 |
| 50 | 70% | fixes 25%, breaks 2% | +6.1 | 26 | 0.6 | 69.1 | 30.3 | 0.0 |
| 50 | 70% | fixes 25%, breaks 5% | +4.0 | 26 | 0.4 | 47.9 | 51.7 | 0.0 |
| 50 | 70% | fixes 50%, breaks 0% | +15.0 | 26 | 18.0 | 81.3 | 0.8 | 0.0 |
| 50 | 70% | fixes 50%, breaks 2% | +13.6 | 26 | 13.2 | 77.9 | 8.9 | 0.0 |
| 50 | 70% | fixes 50%, breaks 5% | +11.5 | 26 | 8.0 | 68.1 | 23.9 | 0.0 |
| 50 | 70% | fixes 90%, breaks 0% | +27.0 | 26 | 84.2 | 15.8 | 0.0 | 0.0 |
| 50 | 70% | fixes 90%, breaks 2% | +25.6 | 26 | 69.4 | 29.9 | 0.7 | 0.0 |
| 50 | 70% | fixes 90%, breaks 5% | +23.5 | 26 | 51.3 | 44.8 | 3.9 | 0.0 |
| 50 | 70% | fixes 0%, breaks 10% | -7.0 | 26 | 0.0 | 0.0 | 99.3 | 0.7 |
| 50 | 70% | fixes 0%, breaks 25% | -17.5 | 26 | 0.0 | 0.0 | 71.4 | 28.6 |
| 50 | 70% | no real change | -0.0 | 26 | 0.0 | 27.4 | 72.6 | 0.0 |
| 80 | 70% | fixes 10%, breaks 0% | +3.0 | 41 | 0.1 | 99.9 | 0.0 | 0.0 |
| 80 | 70% | fixes 10%, breaks 2% | +1.6 | 41 | 0.1 | 67.9 | 32.0 | 0.0 |
| 80 | 70% | fixes 10%, breaks 5% | -0.5 | 41 | 0.0 | 36.6 | 63.3 | 0.1 |
| 80 | 70% | fixes 25%, breaks 0% | +7.5 | 41 | 7.5 | 92.5 | 0.0 | 0.0 |
| 80 | 70% | fixes 25%, breaks 2% | +6.1 | 41 | 4.6 | 83.0 | 12.5 | 0.0 |
| 80 | 70% | fixes 25%, breaks 5% | +4.0 | 41 | 2.2 | 61.7 | 36.1 | 0.0 |
| 80 | 70% | fixes 50%, breaks 0% | +15.0 | 41 | 62.9 | 37.1 | 0.0 | 0.0 |
| 80 | 70% | fixes 50%, breaks 2% | +13.6 | 41 | 44.1 | 54.3 | 1.6 | 0.0 |
| 80 | 70% | fixes 50%, breaks 5% | +11.5 | 41 | 26.3 | 64.8 | 8.8 | 0.0 |
| 80 | 70% | fixes 90%, breaks 0% | +27.0 | 41 | 99.7 | 0.3 | 0.0 | 0.0 |
| 80 | 70% | fixes 90%, breaks 2% | +25.6 | 41 | 95.2 | 4.8 | 0.0 | 0.0 |
| 80 | 70% | fixes 90%, breaks 5% | +23.5 | 41 | 81.9 | 17.7 | 0.4 | 0.0 |
| 80 | 70% | fixes 0%, breaks 10% | -7.0 | 41 | 0.0 | 5.2 | 88.6 | 6.2 |
| 80 | 70% | fixes 0%, breaks 25% | -17.5 | 41 | 0.0 | 0.0 | 25.8 | 74.1 |
| 80 | 70% | no real change | -0.0 | 41 | 0.0 | 42.5 | 57.4 | 0.1 |
| 120 | 70% | fixes 10%, breaks 0% | +3.0 | 61 | 0.9 | 99.1 | 0.0 | 0.0 |
| 120 | 70% | fixes 10%, breaks 2% | +1.6 | 61 | 0.4 | 93.0 | 6.6 | 0.0 |
| 120 | 70% | fixes 10%, breaks 5% | -0.5 | 61 | 0.1 | 65.3 | 34.2 | 0.3 |
| 120 | 70% | fixes 25%, breaks 0% | +7.5 | 61 | 31.6 | 68.5 | 0.0 | 0.0 |
| 120 | 70% | fixes 25%, breaks 2% | +6.1 | 61 | 16.0 | 82.6 | 1.4 | 0.0 |
| 120 | 70% | fixes 25%, breaks 5% | +4.0 | 61 | 6.0 | 81.2 | 12.7 | 0.0 |
| 120 | 70% | fixes 50%, breaks 0% | +15.0 | 61 | 94.2 | 5.8 | 0.0 | 0.0 |
| 120 | 70% | fixes 50%, breaks 2% | +13.6 | 61 | 74.9 | 25.0 | 0.0 | 0.0 |
| 120 | 70% | fixes 50%, breaks 5% | +11.5 | 61 | 46.3 | 52.3 | 1.4 | 0.0 |
| 120 | 70% | fixes 90%, breaks 0% | +27.0 | 61 | 100.0 | 0.0 | 0.0 | 0.0 |
| 120 | 70% | fixes 90%, breaks 2% | +25.6 | 61 | 99.7 | 0.3 | 0.0 | 0.0 |
| 120 | 70% | fixes 90%, breaks 5% | +23.5 | 61 | 96.8 | 3.2 | 0.0 | 0.0 |
| 120 | 70% | fixes 0%, breaks 10% | -7.0 | 61 | 0.0 | 7.0 | 68.2 | 24.8 |
| 120 | 70% | fixes 0%, breaks 25% | -17.5 | 61 | 0.0 | 0.0 | 3.3 | 96.7 |
| 120 | 70% | no real change | -0.0 | 61 | 0.1 | 72.7 | 27.0 | 0.1 |
| 30 | 80% | fixes 10%, breaks 0% | +2.0 | 16 | 0.0 | 3.8 | 96.2 | 0.0 |
| 30 | 80% | fixes 10%, breaks 2% | +0.4 | 16 | 0.0 | 3.1 | 96.9 | 0.0 |
| 30 | 80% | fixes 10%, breaks 5% | -2.0 | 16 | 0.0 | 2.2 | 97.8 | 0.0 |
| 30 | 80% | fixes 25%, breaks 0% | +5.0 | 16 | 0.0 | 19.2 | 80.8 | 0.0 |
| 30 | 80% | fixes 25%, breaks 2% | +3.4 | 16 | 0.0 | 15.0 | 85.0 | 0.0 |
| 30 | 80% | fixes 25%, breaks 5% | +1.0 | 16 | 0.0 | 10.7 | 89.3 | 0.0 |
| 30 | 80% | fixes 50%, breaks 0% | +10.0 | 16 | 0.1 | 50.5 | 49.4 | 0.0 |
| 30 | 80% | fixes 50%, breaks 2% | +8.4 | 16 | 0.0 | 40.4 | 59.5 | 0.0 |
| 30 | 80% | fixes 50%, breaks 5% | +6.0 | 16 | 0.1 | 28.0 | 71.9 | 0.0 |
| 30 | 80% | fixes 90%, breaks 0% | +18.0 | 16 | 2.3 | 82.6 | 15.1 | 0.0 |
| 30 | 80% | fixes 90%, breaks 2% | +16.4 | 16 | 2.2 | 66.3 | 31.5 | 0.0 |
| 30 | 80% | fixes 90%, breaks 5% | +14.0 | 16 | 1.5 | 48.0 | 50.5 | 0.0 |
| 30 | 80% | fixes 0%, breaks 10% | -8.0 | 16 | 0.0 | 0.0 | 99.9 | 0.1 |
| 30 | 80% | fixes 0%, breaks 25% | -20.0 | 16 | 0.0 | 0.0 | 93.0 | 7.0 |
| 30 | 80% | no real change | +0.0 | 16 | 0.0 | 2.8 | 97.2 | 0.0 |
| 50 | 80% | fixes 10%, breaks 0% | +2.0 | 26 | 0.0 | 42.8 | 57.2 | 0.0 |
| 50 | 80% | fixes 10%, breaks 2% | +0.4 | 26 | 0.0 | 29.3 | 70.7 | 0.0 |
| 50 | 80% | fixes 10%, breaks 5% | -2.0 | 26 | 0.0 | 15.8 | 84.1 | 0.0 |
| 50 | 80% | fixes 25%, breaks 0% | +5.0 | 26 | 0.1 | 77.3 | 22.6 | 0.0 |
| 50 | 80% | fixes 25%, breaks 2% | +3.4 | 26 | 0.1 | 54.7 | 45.3 | 0.0 |
| 50 | 80% | fixes 25%, breaks 5% | +1.0 | 26 | 0.0 | 32.8 | 67.2 | 0.0 |
| 50 | 80% | fixes 50%, breaks 0% | +10.0 | 26 | 2.8 | 93.3 | 3.9 | 0.0 |
| 50 | 80% | fixes 50%, breaks 2% | +8.4 | 26 | 2.0 | 76.3 | 21.7 | 0.0 |
| 50 | 80% | fixes 50%, breaks 5% | +6.0 | 26 | 1.1 | 54.9 | 44.0 | 0.0 |
| 50 | 80% | fixes 90%, breaks 0% | +18.0 | 26 | 34.8 | 65.1 | 0.1 | 0.0 |
| 50 | 80% | fixes 90%, breaks 2% | +16.4 | 26 | 24.7 | 70.1 | 5.2 | 0.0 |
| 50 | 80% | fixes 90%, breaks 5% | +14.0 | 26 | 14.1 | 67.9 | 18.0 | 0.0 |
| 50 | 80% | fixes 0%, breaks 10% | -8.0 | 26 | 0.0 | 0.0 | 98.8 | 1.2 |
| 50 | 80% | fixes 0%, breaks 25% | -20.0 | 26 | 0.0 | 0.0 | 59.7 | 40.3 |
| 50 | 80% | no real change | +0.0 | 26 | 0.0 | 25.3 | 74.7 | 0.0 |
| 80 | 80% | fixes 10%, breaks 0% | +2.0 | 41 | 0.0 | 100.0 | 0.0 | 0.0 |
| 80 | 80% | fixes 10%, breaks 2% | +0.4 | 41 | 0.0 | 59.5 | 40.5 | 0.0 |
| 80 | 80% | fixes 10%, breaks 5% | -2.0 | 41 | 0.0 | 26.3 | 73.4 | 0.2 |
| 80 | 80% | fixes 25%, breaks 0% | +5.0 | 41 | 1.3 | 98.7 | 0.0 | 0.0 |
| 80 | 80% | fixes 25%, breaks 2% | +3.4 | 41 | 0.8 | 75.2 | 24.1 | 0.0 |
| 80 | 80% | fixes 25%, breaks 5% | +1.0 | 41 | 0.2 | 44.4 | 55.3 | 0.1 |
| 80 | 80% | fixes 50%, breaks 0% | +10.0 | 41 | 22.4 | 77.6 | 0.0 | 0.0 |
| 80 | 80% | fixes 50%, breaks 2% | +8.4 | 41 | 12.9 | 79.9 | 7.2 | 0.0 |
| 80 | 80% | fixes 50%, breaks 5% | +6.0 | 41 | 6.0 | 67.2 | 26.7 | 0.0 |
| 80 | 80% | fixes 90%, breaks 0% | +18.0 | 41 | 88.1 | 11.9 | 0.0 | 0.0 |
| 80 | 80% | fixes 90%, breaks 2% | +16.4 | 41 | 66.1 | 33.5 | 0.4 | 0.0 |
| 80 | 80% | fixes 90%, breaks 5% | +14.0 | 41 | 38.1 | 57.0 | 4.9 | 0.0 |
| 80 | 80% | fixes 0%, breaks 10% | -8.0 | 41 | 0.0 | 3.5 | 86.5 | 10.0 |
| 80 | 80% | fixes 0%, breaks 25% | -20.0 | 41 | 0.0 | 0.0 | 14.5 | 85.5 |
| 80 | 80% | no real change | +0.0 | 41 | 0.0 | 51.7 | 48.3 | 0.0 |
| 120 | 80% | fixes 10%, breaks 0% | +2.0 | 61 | 0.1 | 99.9 | 0.0 | 0.0 |
| 120 | 80% | fixes 10%, breaks 2% | +0.4 | 61 | 0.1 | 88.2 | 11.8 | 0.0 |
| 120 | 80% | fixes 10%, breaks 5% | -2.0 | 61 | 0.0 | 51.5 | 47.4 | 1.1 |
| 120 | 80% | fixes 25%, breaks 0% | +5.0 | 61 | 7.8 | 92.2 | 0.0 | 0.0 |
| 120 | 80% | fixes 25%, breaks 2% | +3.4 | 61 | 3.4 | 92.5 | 4.1 | 0.0 |
| 120 | 80% | fixes 25%, breaks 5% | +1.0 | 61 | 1.0 | 70.1 | 28.8 | 0.1 |
| 120 | 80% | fixes 50%, breaks 0% | +10.0 | 61 | 62.1 | 37.9 | 0.0 | 0.0 |
| 120 | 80% | fixes 50%, breaks 2% | +8.4 | 61 | 34.5 | 64.9 | 0.6 | 0.0 |
| 120 | 80% | fixes 50%, breaks 5% | +6.0 | 61 | 13.4 | 78.0 | 8.6 | 0.0 |
| 120 | 80% | fixes 90%, breaks 0% | +18.0 | 61 | 99.6 | 0.4 | 0.0 | 0.0 |
| 120 | 80% | fixes 90%, breaks 2% | +16.4 | 61 | 89.4 | 10.6 | 0.0 | 0.0 |
| 120 | 80% | fixes 90%, breaks 5% | +14.0 | 61 | 62.6 | 36.9 | 0.5 | 0.0 |
| 120 | 80% | fixes 0%, breaks 10% | -8.0 | 61 | 0.0 | 3.9 | 60.7 | 35.4 |
| 120 | 80% | fixes 0%, breaks 25% | -20.0 | 61 | 0.0 | 0.0 | 0.9 | 99.1 |
| 120 | 80% | no real change | +0.0 | 61 | 0.0 | 82.9 | 17.1 | 0.1 |
| 30 | 90% | fixes 10%, breaks 0% | +1.0 | 15 | 0.0 | 0.8 | 99.2 | 0.0 |
| 30 | 90% | fixes 10%, breaks 2% | -0.8 | 15 | 0.0 | 0.7 | 99.3 | 0.0 |
| 30 | 90% | fixes 10%, breaks 5% | -3.5 | 15 | 0.0 | 0.5 | 99.5 | 0.0 |
| 30 | 90% | fixes 25%, breaks 0% | +2.5 | 15 | 0.0 | 4.3 | 95.7 | 0.0 |
| 30 | 90% | fixes 25%, breaks 2% | +0.7 | 15 | 0.0 | 3.4 | 96.7 | 0.0 |
| 30 | 90% | fixes 25%, breaks 5% | -2.0 | 15 | 0.0 | 2.1 | 97.9 | 0.0 |
| 30 | 90% | fixes 50%, breaks 0% | +5.0 | 15 | 0.0 | 14.7 | 85.3 | 0.0 |
| 30 | 90% | fixes 50%, breaks 2% | +3.2 | 15 | 0.0 | 11.1 | 88.9 | 0.0 |
| 30 | 90% | fixes 50%, breaks 5% | +0.5 | 15 | 0.0 | 7.6 | 92.4 | 0.0 |
| 30 | 90% | fixes 90%, breaks 0% | +9.0 | 15 | 0.0 | 34.6 | 65.3 | 0.0 |
| 30 | 90% | fixes 90%, breaks 2% | +7.2 | 15 | 0.0 | 27.2 | 72.8 | 0.0 |
| 30 | 90% | fixes 90%, breaks 5% | +4.5 | 15 | 0.0 | 17.9 | 82.1 | 0.0 |
| 30 | 90% | fixes 0%, breaks 10% | -9.0 | 15 | 0.0 | 0.0 | 99.8 | 0.2 |
| 30 | 90% | fixes 0%, breaks 25% | -22.5 | 15 | 0.0 | 0.0 | 88.5 | 11.5 |
| 30 | 90% | no real change | +0.0 | 15 | 0.0 | 0.7 | 99.3 | 0.0 |
| 50 | 90% | fixes 10%, breaks 0% | +1.0 | 26 | 0.0 | 22.8 | 77.2 | 0.0 |
| 50 | 90% | fixes 10%, breaks 2% | -0.8 | 26 | 0.0 | 14.8 | 85.2 | 0.0 |
| 50 | 90% | fixes 10%, breaks 5% | -3.5 | 26 | 0.0 | 7.3 | 92.6 | 0.1 |
| 50 | 90% | fixes 25%, breaks 0% | +2.5 | 26 | 0.0 | 48.6 | 51.4 | 0.0 |
| 50 | 90% | fixes 25%, breaks 2% | +0.7 | 26 | 0.0 | 31.7 | 68.3 | 0.0 |
| 50 | 90% | fixes 25%, breaks 5% | -2.0 | 26 | 0.0 | 17.0 | 83.0 | 0.1 |
| 50 | 90% | fixes 50%, breaks 0% | +5.0 | 26 | 0.0 | 74.4 | 25.6 | 0.0 |
| 50 | 90% | fixes 50%, breaks 2% | +3.2 | 26 | 0.0 | 50.9 | 49.0 | 0.0 |
| 50 | 90% | fixes 50%, breaks 5% | +0.5 | 26 | 0.0 | 27.4 | 72.6 | 0.0 |
| 50 | 90% | fixes 90%, breaks 0% | +9.0 | 26 | 1.0 | 89.6 | 9.4 | 0.0 |
| 50 | 90% | fixes 90%, breaks 2% | +7.2 | 26 | 0.8 | 68.3 | 30.9 | 0.0 |
| 50 | 90% | fixes 90%, breaks 5% | +4.5 | 26 | 0.3 | 44.5 | 55.2 | 0.0 |
| 50 | 90% | fixes 0%, breaks 10% | -9.0 | 26 | 0.0 | 0.0 | 97.7 | 2.3 |
| 50 | 90% | fixes 0%, breaks 25% | -22.5 | 26 | 0.0 | 0.0 | 47.5 | 52.5 |
| 50 | 90% | no real change | +0.0 | 26 | 0.0 | 17.7 | 82.3 | 0.0 |
| 80 | 90% | fixes 10%, breaks 0% | +1.0 | 41 | 0.0 | 100.0 | 0.0 | 0.0 |
| 80 | 90% | fixes 10%, breaks 2% | -0.8 | 41 | 0.0 | 50.7 | 49.3 | 0.0 |
| 80 | 90% | fixes 10%, breaks 5% | -3.5 | 41 | 0.0 | 17.5 | 81.8 | 0.7 |
| 80 | 90% | fixes 25%, breaks 0% | +2.5 | 41 | 0.0 | 100.0 | 0.0 | 0.0 |
| 80 | 90% | fixes 25%, breaks 2% | +0.7 | 41 | 0.0 | 58.5 | 41.4 | 0.0 |
| 80 | 90% | fixes 25%, breaks 5% | -2.0 | 41 | 0.0 | 24.8 | 74.8 | 0.4 |
| 80 | 90% | fixes 50%, breaks 0% | +5.0 | 41 | 0.9 | 99.1 | 0.0 | 0.0 |
| 80 | 90% | fixes 50%, breaks 2% | +3.2 | 41 | 0.4 | 73.9 | 25.7 | 0.0 |
| 80 | 90% | fixes 50%, breaks 5% | +0.5 | 41 | 0.1 | 40.0 | 59.8 | 0.1 |
| 80 | 90% | fixes 90%, breaks 0% | +9.0 | 41 | 14.3 | 85.7 | 0.0 | 0.0 |
| 80 | 90% | fixes 90%, breaks 2% | +7.2 | 41 | 7.7 | 82.5 | 9.7 | 0.0 |
| 80 | 90% | fixes 90%, breaks 5% | +4.5 | 41 | 2.6 | 62.6 | 34.8 | 0.0 |
| 80 | 90% | fixes 0%, breaks 10% | -9.0 | 41 | 0.0 | 2.2 | 82.8 | 15.1 |
| 80 | 90% | fixes 0%, breaks 25% | -22.5 | 41 | 0.0 | 0.0 | 8.3 | 91.7 |
| 80 | 90% | no real change | +0.0 | 41 | 0.0 | 68.6 | 31.4 | 0.0 |
| 120 | 90% | fixes 10%, breaks 0% | +1.0 | 61 | 0.0 | 100.0 | 0.0 | 0.0 |
| 120 | 90% | fixes 10%, breaks 2% | -0.8 | 61 | 0.0 | 80.0 | 19.9 | 0.1 |
| 120 | 90% | fixes 10%, breaks 5% | -3.5 | 61 | 0.0 | 35.9 | 61.0 | 3.1 |
| 120 | 90% | fixes 25%, breaks 0% | +2.5 | 61 | 0.4 | 99.6 | 0.0 | 0.0 |
| 120 | 90% | fixes 25%, breaks 2% | +0.7 | 61 | 0.1 | 87.9 | 12.0 | 0.0 |
| 120 | 90% | fixes 25%, breaks 5% | -2.0 | 61 | 0.0 | 49.3 | 49.5 | 1.2 |
| 120 | 90% | fixes 50%, breaks 0% | +5.0 | 61 | 7.2 | 92.8 | 0.0 | 0.0 |
| 120 | 90% | fixes 50%, breaks 2% | +3.2 | 61 | 2.9 | 92.3 | 4.7 | 0.0 |
| 120 | 90% | fixes 50%, breaks 5% | +0.5 | 61 | 0.6 | 65.4 | 33.8 | 0.2 |
| 120 | 90% | fixes 90%, breaks 0% | +9.0 | 61 | 56.8 | 43.2 | 0.0 | 0.0 |
| 120 | 90% | fixes 90%, breaks 2% | +7.2 | 61 | 25.6 | 73.6 | 0.8 | 0.0 |
| 120 | 90% | fixes 90%, breaks 5% | +4.5 | 61 | 7.0 | 80.1 | 12.9 | 0.0 |
| 120 | 90% | fixes 0%, breaks 10% | -9.0 | 61 | 0.0 | 2.1 | 51.2 | 46.7 |
| 120 | 90% | fixes 0%, breaks 25% | -22.5 | 61 | 0.0 | 0.0 | 0.2 | 99.8 |
| 120 | 90% | no real change | +0.0 | 61 | 0.0 | 92.7 | 7.3 | 0.0 |

Can't tell yet counts all three of its kinds (leans better, looks the same, leans worse). Each row is one first test on a new set of marks kept aside; later tests on the same marks are stricter.
