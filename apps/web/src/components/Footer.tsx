"use client";

import { ArrowUpRight } from "lucide-react";
import { Brand, BrandMark } from "./icons";

export function FinalCta() {
  return (
    <section className="container final-cta" aria-labelledby="final-heading">
      <BrandMark className="final-mark" />
      <h2 id="final-heading">
        Start with one sentence.
        <br />
        See where it takes you.
      </h2>
      <p>No setup to get through. Just a small thing to try.</p>
      <a className="btn btn-primary" href="#playground">
        Make your first decision <ArrowUpRight aria-hidden="true" />
      </a>
    </section>
  );
}

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="container">
        <div className="footer-top">
          <Brand />
          <div className="footer-links">
            <a href="#playground">Playground</a>
            <a href="#examples">Examples</a>
            <a href="https://docs.typesafe.ai/" target="_blank" rel="noopener noreferrer">
              TypeSafe docs
            </a>
            <a href="mailto:support@typesafe.pro">support@typesafe.pro</a>
            <a href="#faq-independent">About this gateway</a>
          </div>
        </div>
        <div className="footer-bottom">
          <p>
            An independent gateway to TypeSafe Jev. Jev is developed by TypeSafe AI.
            <br />
            Built for learning and testing. Always check important decisions.
          </p>
          <p>(c) 2026 typesafe.pro / Small questions. Useful answers.</p>
        </div>
      </div>
    </footer>
  );
}
