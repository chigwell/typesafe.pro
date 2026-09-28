import type { UseCaseDemo, UseCasePage } from "@/lib/use-case-types";

export function useCaseDemoFixture(): UseCaseDemo {
  const questions = { mood: { type: "noul" as const, instructions: "Is the message positive?" } };
  const sample = (message: string, description: string) => ({
    request: { model: "jev-latest" as const, state: { message }, questions },
    description,
    expected: { mood: { type: "noul" as const, min: 0.8, max: 1 } },
    response: { model: "jev-test", answers: { mood: { type: "noul" as const, noul: 0.93 } } },
    verified_at: "2026-09-25T12:00:00Z",
  });
  return {
    title: "Mood bar", concept: "A bar grows with how positive the message is.", interaction: "Type a short message and press Check.", visual: "The bar width follows the noul probability.",
    questions,
    html: '<label>Message <input id="demo-input" type="text"></label><button id="demo-run" type="button">Check</button><p id="demo-status"></p><div id="demo-visual"></div>',
    css: "#demo-visual{height:40px;background:var(--demo-accent)}",
    js: 'const run = document.getElementById("demo-run"); run.addEventListener("click", async () => { const answers = await window.TypeSafeDemo.evaluate({ message: document.getElementById("demo-input").value }); document.getElementById("demo-visual").style.width = Math.round(answers.mood.noul * 100) + "%"; });',
    samples: [sample("Thanks, this was fast!", "A clearly positive message."), sample("Great support, thank you.", "Another positive message.")],
    verified_at: "2026-09-25T12:00:00Z",
  };
}

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
