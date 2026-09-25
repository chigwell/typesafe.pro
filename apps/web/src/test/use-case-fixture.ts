import type { UseCasePage } from "@/lib/use-case-types";

export function useCaseFixture(slug = "sort-maintenance-requests"): UseCasePage {
  return {
    schema_version: 1, slug, industry: "Property management", audience: "Maintenance coordinators", task_type: "route-request",
    search_intent: "Route maintenance requests with typed decisions", summary: "Route a reported problem to the appropriate maintenance queue.",
    problem: "A coordinator needs to direct written reports to the right team.", input_description: "A resident's maintenance request.", decision: "Choose plumbing, electrical, or review.", action: "Add the request to the suggested queue for a coordinator to review.",
    seo: { title: "Route Maintenance Requests with TypeSafe", description: "Use TypeSafe Jev to route maintenance reports into typed queues. Explore three verified examples, API requests, and code in seven programming languages." },
    intro: "A leaky tap and a broken light need different teams. A small typed decision can help sort the incoming reports.", solution: "Define each queue in Choice criteria and supply the report as state. Keep a review option for unclear reports.",
    limitations: ["Routing does not determine urgency or replace a coordinator's review."],
    examples: (["primary", "alternative", "edge"] as const).map((kind) => ({ name: `${kind} input`, kind, request: { model: "jev-latest", state: kind === "edge" ? "Something needs attention." : "The sink is leaking.", questions: { queue: { type: "choice", instructions: "Which team should review this report?", criteria: { plumbing: "Water or pipes.", review: "Unclear request." } } } }, expected: { queue: { type: "choice", choice: kind === "edge" ? "review" : "plumbing" } }, expected_description: kind === "edge" ? "Send unclear reports for review." : "Suggest the plumbing queue.", response: { model: "jev-test", answers: { queue: { type: "choice", choice: kind === "edge" ? "review" : "plumbing", probabilities: { plumbing: kind === "edge" ? 0.1 : 0.9, review: kind === "edge" ? 0.9 : 0.1 }, confidence: 0.8 } } }, verified_at: "2026-09-25T12:00:00Z" })),
    verification: { model: "jev-test", verified_at: "2026-09-25T12:00:00Z", quality: { useful: 0.95, supported: 0.99, consistent: 0.96 }, novelty_probability: 1 }, created_at: "2026-09-25T12:00:00Z", updated_at: "2026-09-25T12:00:00Z",
  };
}
