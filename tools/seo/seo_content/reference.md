# TypeSafe.pro reference for generated examples, version 1

Sources checked 2026-09-25: https://docs.typesafe.ai/api,
https://docs.typesafe.ai/primitives/noul, https://docs.typesafe.ai/cookbooks/rerank_typesafe,
and this repository's public API validation and TypeScript playground contract.

POST https://api.typesafe.pro/v1/systemone accepts JSON:
{"model":"jev-latest","state": "text or a JSON object/array", "questions": {"id": question}}.
Generated browser playground examples are limited to 20 questions and 65536 request
bytes; server admission limits are separate. Browser examples use the public proxy
without embedding a credential. Service generation uses its admin token.

A question's instructions accept a string, object or array. Question IDs are for code;
they do not convey meaning to the model. Refer to named state fields in the instructions.

Choice: {"type":"choice","instructions":"Which route?","criteria":{"route_a":"description","route_b":"description"}}.
Criteria are 1–255 named options. An option description may be a string, object, array or null.
Answer: {"type":"choice","choice":"route_a","probabilities":{"route_a":0.9,"route_b":0.1},"confidence":0.8}.

Noul: {"type":"noul","instructions":"Does the condition hold?"}.
Optional criteria object describes "true" and "false". It returns probability of yes,
not a generated explanation and not a separate confidence value.
Answer: {"type":"noul","noul":0.9}. A value near 0.5 signals uncertainty about yes/no.

Score: {"type":"score","instructions":"How complete is this report?","criteria":["Missing essentials","Partly complete","All essentials present"]}.
Criteria are 2–10 ordered descriptive levels. Answer has type "score", score in [0, number of criteria minus 1],
probabilities, confidence and legend. The score is a probability-weighted
level index (for 5 criteria, 0 through 4). It is not a freeform numeric prediction.

The response has model, answers keyed by question ID, and optional input_tokens/output_tokens
inside usage. Independent questions in a single request cannot see one another's answers.

Use semantic judgments for routing, ranking, extraction from supplied candidate values,
verification and classification. Ordinary code controls policy, deterministic calculations,
execution and escalation. A type-safe answer does not guarantee factual correctness.
Typed output format does NOT imply deterministic model decisions: judgments and
probabilities may vary across evaluations. The API returns judgments; application code
executes routing, updates records, sends notifications or escalates cases. A single Choice question selects one supplied option. Multiple independent Noul questions
can support a multi-label workflow. The independence of batched questions only means
one question cannot read another's answer; it does not establish a blanket reasoning
incapability. A fallback/review choice is an application design option, not a mandatory
API field or universal requirement.

Mentioning an identifier in text establishes only that it was mentioned, not that the
identifier is valid, the corresponding project/account is active, or its use is authorized.
Checking that fields or stated reasons are present establishes text completeness, not
eligibility, compliance, policy approval or permission to act. Those conclusions require
relevant authoritative records/policy in the supplied state and questions that actually
evaluate that evidence. A caller's self-reported assertion alone is not authoritative
validation. Application code or a reviewer must perform any still-missing authoritative
checks before treating a completeness judgment as permission to execute an action.

## Authoring guidance

Examples must be small, fictional, privacy-safe and executable using only the supplied
state. Give Choice a no-match outcome when relevant. Use concrete descriptions for Score
levels. Each question should ask one atomic, well-defined judgment. Include a genuinely
different alternative input and an edge input. An edge may be missing context or a
no-match case with an explicit review/no-match option; it need not be an ambiguous
probability in the middle of a range. Missing context does not imply any particular
Noul probability or Score value; do not invent that numerical behavior.
Expected numeric ranges must be meaningful; never accept the entire possible rubric as verification. Treat
saved responses as observed examples, not guaranteed future outputs. Do not claim latency,
accuracy, pricing, unlimited use, regulatory compliance or provider availability guarantees.
Do not describe Jev as generating text, arbitrary JSON or explanations.

Write plain-text paragraphs and lists, not HTML/Markdown links or executable code. The
site generates all seven language snippets deterministically from EvaluationRequest.

Editorial style: start with the user's concrete problem, not a product or interface
overview. The introduction uses 2–3 short sentences; the problem uses 2–4; the solution
uses 3–5 simple sentences tied to the observed examples and a downstream code action.
Include 2–3 specific limitations about this task's inputs, available options or review
boundary. Avoid generic AI prose, inflated adjectives and unsupported model limitations.

Use exactly identical question IDs, instructions and criteria across all three example
requests; only the state changes. If a review/no-match option is useful, include it in
every request. The explanation must distinguish the behavior of this particular
request from the model's overall capabilities. A limitation of a single Choice is not
a model-wide inability to classify multiple labels using other question designs.
Suggested review policies are optional application choices, not mandatory API rules.

Do not make unsupported outcome guarantees with words such as "ensures" or "always".
Describe saved results as observations and application actions as conditional policies.
Example names and expected descriptions must literally match their inputs: punctuation-only
text such as "..." is not empty input. State precisely whether an input is irrelevant,
missing substantive details, or contains an explicit value; do not mislabel these cases.

Keep evidence and conclusions aligned throughout the title, prose, examples and next action.
An identifier-presence check does not validate its existence, active status or authorization.
Completeness-only examples should use labels such as ready_for_review or missing_details,
not approved or authorized. If an example claims eligibility, compliance or approval,
include the decisive authoritative records/policy in state and actually evaluate them.
Otherwise frame the result as triage and describe the separate authoritative validation
that remains necessary; do not imply it already happened.
