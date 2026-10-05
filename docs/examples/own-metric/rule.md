---
rubric_version: refund-policy-v1
---
You are checking one thing about an AI response to an instruction: the reply states the refund rule the policy gives for the customer's case, and it promises no refund the policy does not allow.

Decide whether the response passes or fails on that one thing only. Ignore everything else about the response.

# What counts as pass
The reply names the rule that applies to the customer's item (the 30-day window for an unopened item, the 14-day window for opened electronics, no refund for a started digital download, exchange only for a sale item) and its answer follows that rule. A short or plain reply is fine.

# What counts as fail
The reply gives a different window from the policy, leaves the rule out, or promises a refund, an exception or a shipping refund that the policy does not allow. A friendly tone does not make a wrong reply pass.

# Examples
Pass:
- "Unopened items can be returned for a full refund within 30 days of delivery, and yours was delivered 10 days ago, so it qualifies."
- "Digital downloads cannot be refunded once the download has started, so we are not able to refund this purchase."
- "Sale items cannot be refunded. They can be exchanged within 14 days of delivery."

Fail:
- "You can return it for a full refund within 60 days." (the policy says 30 days)
- "That is outside the window, but we will make an exception and refund you in full." (an exception the policy does not allow)
- "I am so sorry about this. I have arranged a full refund for you today." (a refund the policy does not allow, and no rule stated)

# Edge cases
A reply that states the right window and then promises a refund anyway fails: the promise is what the customer will hold us to. A reply that refuses a refund the policy allows also fails, because it states the wrong rule for the case. Shipping charges are never refunded, so a reply that includes them in the refund fails. The reply does not need to quote the policy word for word.

# Instruction
{{input}}

# Response
{{output}}

Explain your reasoning in a few sentences. Then end your reply with exactly one line, either `Verdict: pass` or `Verdict: fail`.
