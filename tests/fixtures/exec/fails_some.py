# Exits non-zero on items whose id ends in 1: those become error judgments.
import json
import sys

item = json.load(sys.stdin)
if item["id"].endswith("1"):
    print("judge crashed", file=sys.stderr)
    sys.exit(3)
print("pass" if "good" in item["output"] else "fail")
