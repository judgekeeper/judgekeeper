"""promptfoo `exec:` provider: answers each question. No model, no API call.

promptfoo calls `python3 answerer.py <prompt> <options json> <context json>` and reads stdout.
"""

import sys

prompt = sys.argv[1]
question = prompt.split("Question:", 1)[1].strip()
print(f"My answer to: {question}")
