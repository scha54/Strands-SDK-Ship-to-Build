# Demo script

Total timed walkthrough: **170 seconds** (limit 180, R-12.5). Each step shows its duration as
`(N s)`; the docs check test sums them.

Before you start, say which mode you are in. Stub mode and Demo_Fallback are not live Bedrock
execution, and you must say so out loud when they apply.

Setup once: follow [README: Start Demo_Mode](../README.md#start-demo_mode-all-five-stages).
For the screens, open `http://localhost:5173/harness.html?screen=live&backend=ok`.

## Timed steps

1. [0:00-0:15] (15 s) Frame the problem: a facilitator has everyday objects and no curriculum.
   State that every lesson is supervised and that this is a prototype with no efficacy claim.
2. [0:15-0:30] (15 s) Press **Fill Demo Mode preset**. Point out age 6-8, mathematics and seven
   objects (Stone 1 to 5, Leaf 1 and 2). Press **Start session**.
3. [0:30-1:00] (30 s) Watch the five-stage timeline: understand objects, choose objective,
   create story, assess answer, adapt next activity. State the execution mode shown: stub
   (deterministic, offline), live (Bedrock), or fallback (label `Demo fallback — no live agent
   execution`). Note that stages show names and status only, no prompts or reasoning.
4. [1:00-1:20] (20 s) Baseline question, then the first Activity: one Activity at a time,
   "1 of 3", supervision notice, no expected answer visible.
5. [1:20-1:45] (25 s) Enter a wrong answer. Show the explanation, then request a hint (it never
   contains the answer). Mention that exact answers are graded by code, not by a model.
6. [1:45-2:05] (20 s) Show the adapted next Activity: same objective, different scaffold, and
   the note reported to the facilitator. It passed the same gates.
7. [2:05-2:25] (20 s) Complete the end check and open the summary: concepts practiced, next
   step, provisional estimate. If the baseline and end check were both answered, show the
   observed difference and its not-validated warning. Do not describe it as improvement.
8. [2:25-2:40] (15 s) Show Stop, End and Delete, then delete the session.
9. [2:40-2:50] (10 s) Close with the evidence split: gate pass rates are measured on synthetic
   stubbed cases; latency and cost figures are illustrative; live Bedrock results exist only if
   the opt-in live run was done and are reported separately.

## What not to say

- Do not say the system improves learning, is validated, or diagnoses anything.
- Do not present stub or fallback runs as live agent execution.
- Do not quote stubbed latency or cost as real performance.

## Fallback rehearsal

To show Demo_Fallback deliberately, make the model unavailable (for example run with
`backend=fail`, or a live run with no AWS credentials). The label must appear on every stage
screen. Rehearse both paths before presenting.
