# Reads one item as JSON on stdin and prints a bare verdict.
import json
import sys

item = json.load(sys.stdin)
print("PASS" if "good" in item["output"] else "FAIL")
