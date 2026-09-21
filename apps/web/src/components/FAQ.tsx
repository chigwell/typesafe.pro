"use client";

import { Plus } from "lucide-react";
import { useState } from "react";

const FAQS = [
  {
    id: "faq-chatbot",
    question: "Is this a chatbot?",
    answer:
      "No. Jev answers small, focused questions about text. It returns a label, a score, or a probability, not a written reply. Use a generative model for writing, and use these answers for decisions in your code.",
  },
  {
    id: "faq-free",
    question: "Do I need an account or a credit card?",
    answer:
      "You can explore the examples without either. typesafe.pro is designed for free learning and testing, including anonymous HTTP access. Live access is subject to gateway availability and fair-use limits.",
  },
  {
    id: "faq-own-text",
    question: "Can I try my own text?",
    answer:
      "Yes: switch the playground to Live API. Sample mode contains hand-written examples to explain the interface; it does not run a model or evaluate new text.",
  },
  {
    id: "faq-accuracy",
    question: "Can the answers be wrong?",
    answer:
      "Yes. A high probability or confidence value is not proof that a decision is correct. Try representative examples, keep the original input, and send important or unclear decisions to a person.",
  },
  {
    id: "faq-advanced",
    question: "What does Advanced mode add?",
    answer:
      "You can edit the full JSON request, change the model, define your own labels or score levels, and ask multiple independent questions about the same input.",
  },
  {
    id: "faq-independent",
    question: "Is this the official TypeSafe website?",
    answer:
      "No. typesafe.pro is an independent access gateway. Jev is developed by TypeSafe AI, and the linked TypeSafe documentation describes their upstream models and API.",
  },
];

export function FAQ() {
  const [open, setOpen] = useState(() => new Set(["faq-chatbot"]));

  return (
    <section className="section container" id="faq" aria-labelledby="faq-heading">
      <div className="faq-layout">
        <div className="faq-intro">
          <p className="eyebrow">Good questions</p>
          <h2 className="section-title" id="faq-heading">
            A little more
            <br />
            context.
          </h2>
          <p>No mystery. Here is what you are trying, and where it fits.</p>
        </div>
        <div className="faq-list">
          {FAQS.map((item) => {
            const expanded = open.has(item.id);
            return (
              <article className={`faq-item ${expanded ? "is-open" : ""}`} id={item.id} key={item.id}>
                <h3>
                  <button
                    type="button"
                    className="faq-question"
                    id={`${item.id}-question`}
                    aria-controls={`${item.id}-answer`}
                    aria-expanded={expanded}
                    onClick={() =>
                      setOpen((current) => {
                        const next = new Set(current);
                        if (next.has(item.id)) next.delete(item.id);
                        else next.add(item.id);
                        return next;
                      })
                    }
                  >
                    {item.question}
                    <Plus aria-hidden="true" />
                  </button>
                </h3>
                <div className="faq-answer" id={`${item.id}-answer`} role="region" aria-labelledby={`${item.id}-question`} hidden={!expanded}>
                  <p>{item.answer}</p>
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </section>
  );
}

