# M1 model check (D9)

Does the model pick the right tool with valid arguments, and how many requests and tokens does a conversation take? The check runs on canned tool results, before any database exists (milestones.md).

## Pass threshold (copied verbatim from milestones.md, written before the check runs)

- **Check set:** 20 single-step cases. Each case has a customer message, the tool the model should call, and the key arguments it should pass. The set includes cases where `request_refund` must *not* be called and cases where `create_handoff` must be called. Each model (Flash-Lite and Groq gpt-oss) runs the full set 3 times.
- **A malformed tool call counts as a fail** (D3).
- **Pass threshold (T1), per model:** a mean of at least 90% over the 3 runs, **and** zero cases where `request_refund` is called when it shouldn't be.

## Scoring rule (`scoring.py`)

- Only the model's **first** tool call is scored for pass/fail.
- It must name `expected_tool`, its arguments must validate against the tool's schema, and every key in `expected_args` must match exactly. `item_ids` is compared as a set. There's no trimming or case folding.
- A `request_refund` call anywhere in the reply, on a case that doesn't expect one, fails with `wrong_refund`. That reason takes precedence over every other reason, and the call counts even if it's malformed.
- Fail reasons: `no_tool_call`, `wrong_tool`, `wrong_args`, `malformed`, `wrong_refund`. `error` means a provider error that was still failing after 2 reruns. It is not counted in N, and a run with more than 2 errors is invalid (D3).
- A repeated eligibility check on a `request_refund` case is `wrong_tool`. The case history shows the check already ran (decided 26 Nov 2026).

## Files

| File | What it holds |
|---|---|
| `cases.yaml` | The 20 cases. History is a real earlier tool exchange (decided 26 Nov 2026). |
| `conversations.yaml` | 5 scripted conversations with canned results. They measure requests and tokens and aren't scored. |
| `system_prompt.md` | The agent prompt. Its first line is the version, which goes into every result file. |
| `models.yaml` / `models.md` | The pinned model settings, and their sources. |

The numbers this check produces are early estimates: draft prompt, canned tool results (milestones.md).
