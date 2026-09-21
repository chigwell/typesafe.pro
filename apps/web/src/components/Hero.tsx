"use client";

import { ArrowDown, ArrowRight, ArrowUpRight, Check, Mail, Tag } from "lucide-react";

export function Hero() {
  return (
    <section className="hero container" aria-labelledby="hero-heading">
      <div className="hero-content">
        <a className="hero-eyebrow" href="#faq-free">
          <span className="dot" aria-hidden="true" />
          Free access to TypeSafe Jev <ArrowUpRight aria-hidden="true" />
        </a>
        <h1 id="hero-heading">
          Messy words.
          <br />
          <span className="accent">Clear decisions.</span>
        </h1>
        <p className="hero-description">
          Is this urgent? Which label fits? How positive is it?
          <br />
          Give your app useful answers, not another paragraph.
        </p>
        <div className="hero-ctas">
          <a className="btn btn-primary" href="#playground">
            Try it for yourself <ArrowDown aria-hidden="true" />
          </a>
          <a className="btn btn-ghost" href="#how-it-works">
            How it works <ArrowUpRight aria-hidden="true" />
          </a>
        </div>
        <p className="hero-note">Free for learning and testing. No account needed to explore.</p>
        <div className="hero-flows" aria-label="Add text, ask one thing, get an answer">
          <span className="hero-flow">
            <span className="flow-number">1</span>Add some text
          </span>
          <ArrowRight aria-hidden="true" />
          <span className="hero-flow">
            <span className="flow-number">2</span>Ask one thing
          </span>
          <ArrowRight aria-hidden="true" />
          <span className="hero-flow">
            <span className="flow-number">3</span>Get a useful answer
          </span>
        </div>
      </div>
      <div className="float-note" aria-hidden="true">
        <div className="note-caption">
          <Mail />a customer message
        </div>
        <p>
          "Could I get
          <br />a refund?"
        </p>
        <div className="note-lines" />
      </div>
      <div className="float-answer" aria-hidden="true">
        <div className="answer-stamp">
          <Check />
        </div>
        <div className="answer-label">
          <Tag />
          refund
        </div>
      </div>
    </section>
  );
}
