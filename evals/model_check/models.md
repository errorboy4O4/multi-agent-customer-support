# M1 check models: pinned settings and their sources

The values here are read by the code from [`models.yaml`](models.yaml). This file records where each value came from. Both files change together, and only as a recorded decision.

Public docs were read on 26 Nov 2026. Muse read them first, and Claude then fetched the provider pages again to check each value. Console readings were added by the owner from their own accounts on 26 Nov 2026.

## Gemini: `gemini-3.5-flash-lite`

| Setting | Pinned | Source and reason |
|---|---|---|
| Model ID | `gemini-3.5-flash-lite` | Listed as **Stable** on the [model page](https://aistudio.google.com/docs/models/gemini-3.5-flash-lite) and the [Cloud model page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite). |
| Temperature | `null` (nothing sent) | **Not settable on this model.** The [Cloud model page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite) says custom temperature, top-K and top-P values aren't supported and are ignored, and lists the fixed defaults: temperature 1.0, topP 0.95, topK 64. The [Gemini 3.6 notes](https://aistudio.google.com/docs/whats-new-gemini-3.6) call these parameters deprecated and say to remove them from requests, because future model generations will return an error. So nothing is sent (D3: pin sampling only where the provider allows it). |
| Effort | `medium` | Sent as `thinking_level`. The levels are minimal, low, medium and high, and the default is minimal ([thinking page](https://aistudio.google.com/docs/thinking)). The [Cloud model page](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-5-flash-lite) recommends medium or high for subagents and warns that minimal "can cause premature tool termination on multi-step tasks". Medium is the lowest level recommended for tool calling. LangChain's `reasoning_effort="medium"` was checked offline to become `thinking_level=MEDIUM` in the request. |
| Retirement | none announced | The [Gemini API deprecations page](https://aistudio.google.com/docs/deprecations) lists release date 21 July 2026 and "No shutdown date announced". No retirement date was found on the Cloud page either. |
| Free-tier limits | **15 RPM, 250K TPM, 500 RPD** (seen in my console, 26 Nov 2026) | Read by the owner from the AI Studio Rate Limit page of the development project, Free tier. Usage over the previous 28 days was zero. Google publishes no free-tier figures for this model, and these limits apply per project. |

## Groq: `openai/gpt-oss-120b`

| Setting | Pinned | Source and reason |
|---|---|---|
| Model ID | `openai/gpt-oss-120b` | Listed under **Production Models** on the [models page](https://console.groq.com/docs/models). |
| Temperature | `0.6` | The ["Recommended Configuration Parameters" table on the reasoning page](https://console.groq.com/docs/reasoning) gives 0.6, with a recommended range of 0.5–0.7 "to prevent repetitions or incoherent outputs". That table covers Groq's reasoning models in general, not 120b alone. The API's own default is 1 ([API reference](https://console.groq.com/docs/api-reference)), so the recommended value is pinned rather than left to the API default. |
| Effort | `medium` | Sent as `reasoning_effort`. The [API reference](https://console.groq.com/docs/api-reference) says the gpt-oss models support low, medium and high, with medium as the default. (The reasoning page's general table lists the default as `default`; the API reference is the more specific source.) Medium is the documented default, and the same level as Gemini's. The two providers' levels aren't calibrated against each other, though, so "medium" doesn't mean equal effort. |
| Retirement | none announced | Not on the [deprecations page](https://console.groq.com/docs/deprecations). It is named there as the recommended replacement for several deprecated models. |
| Free-tier limits | **30 RPM, 1K RPD, 8K TPM, 200K TPD** (seen in my console, 26 Nov 2026) | Read by the owner from the console's Organization Limits page. These are the organisation base limits. The "Show Current Project Limits" toggle was off, so any lower limit set on a project wasn't shown. They match the [rate-limits page](https://console.groq.com/docs/rate-limits). |

## Thought signatures (Gemini)

Checked 26 Nov 2026 on the [Google Cloud thought-signature page](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/thought-signatures):
- The rule: Gemini 3 needs a signature on the first function call of each step in the **current turn**, or it returns a `400`. A turn begins with the most recent user message that is not a function response.
- What the page doesn't say: that function calls in earlier turns go unvalidated. That's inferred from the wording.
- The placeholder: for history the model never produced, the page documents `skip_thought_signature_validator` as a last resort that hurts quality. langchain-google-genai inserts it only for current-turn calls that lack a signature.
- Text parts: their signatures are recommended but not enforced.

What this means for the check:
- The cases' hand-written history sits before the customer's latest message, so it's outside the current turn and needs no placeholder. One live request on case `rr-01` was accepted (26 Nov 2026).
- Live conversations append each model reply unchanged, so the model's own signatures go back with it.

## Not recorded (and why)

- **A Gemini retirement date of "21 July 2027 or later"**: not found on either Google page in this check. 21 July 2026 is the release date.
- **Third-party Gemini free-tier figures** (Sep–Oct 2026): not used as a source. The console reading above happens to give the same values. D9 judges whether the quota is enough from measured request and token counts.
