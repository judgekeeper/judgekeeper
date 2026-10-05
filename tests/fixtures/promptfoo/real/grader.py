"""promptfoo `exec:` llm-rubric grader returning {"pass", "score", "reason"}. No API call.

Verdicts are fixed per question and per call (the call count per question is kept in
grader-state.json, so run with -j 1 and delete the state file first): the grader passes
Q0, Q1, Q5 on every call, and passes Q2 on its second call only.
"""

import json
import re
import sys
from pathlib import Path

STATE = Path(__file__).with_name("grader-state.json")

prompt = sys.argv[1]
qid = re.search(r"\b(Q\d+)\b", prompt).group(1)
state = json.loads(STATE.read_text()) if STATE.exists() else {}
state[qid] = state.get(qid, 0) + 1
STATE.write_text(json.dumps(state))

passes = qid in {"Q0", "Q1", "Q5"} or (qid == "Q2" and state[qid] == 2)
print(json.dumps({"pass": passes, "score": 1 if passes else 0,
                  "reason": f"{qid} call {state[qid]}: {'helpful' if passes else 'not helpful'}"}))
