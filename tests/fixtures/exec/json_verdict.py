# Reads one item as JSON on stdin and prints a JSON verdict with a reason.
import json
import sys

item = json.load(sys.stdin)
ok = "good" in item["output"]
print(json.dumps({"verdict": "pass" if ok else "fail", "reason": f"saw {item['id']}"}))
