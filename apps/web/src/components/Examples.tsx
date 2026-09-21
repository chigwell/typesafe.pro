"use client";

import { ArrowDown, ArrowRight, ArrowUpRight, Search } from "lucide-react";
import type { CSSProperties } from "react";
import { useMemo, useState } from "react";
import { PRESETS } from "@/lib/presets";
import { PresetIcon } from "./icons";
import type { ExampleSelection } from "./Playground";

type Filter = "all" | "support" | "everyday" | "developers";

export function Primitives() {
  return (
    <section className="section container" id="how-it-works" aria-labelledby="how-heading">
      <div className="section-head center">
        <p className="eyebrow">How it works</p>
        <h2 className="section-title" id="how-heading">
          Three small primitives.
          <br />
          Lots of useful decisions.
        </h2>
      </div>
      <div className="primitive-grid">
        <article className="primitive-card">
          <div className="primitive-art choice-art">
            <span>technical</span>
            <span className="selected">billing</span>
            <span>other</span>
          </div>
          <span className="api-name">01 / Choice</span>
          <h3>Pick a label.</h3>
          <p>Choose from the options you define.</p>
        </article>
        <article className="primitive-card">
          <div className="primitive-art noul-art">
            <span className="yes">yes</span>
            <span className="no">no</span>
          </div>
          <span className="api-name">02 / Noul</span>
          <h3>Check a yes / no.</h3>
          <p>Get the probability that the answer is yes.</p>
        </article>
        <article className="primitive-card">
          <div className="primitive-art score-art">
            <span style={{ "--height": "30px" } as CSSProperties} />
            <span style={{ "--height": "46px" } as CSSProperties} />
            <span style={{ "--height": "67px" } as CSSProperties} />
            <span style={{ "--height": "91px" } as CSSProperties} />
          </div>
          <span className="api-name">03 / Score</span>
          <h3>Put it on a scale.</h3>
          <p>Define levels, then get a score between them.</p>
        </article>
      </div>
      <p className="primitives-note">
        Jev makes a judgement. Your code decides what happens next.{" "}
        <a href="https://docs.typesafe.ai/primitives" target="_blank" rel="noopener noreferrer">
          Meet the primitives
        </a>
      </p>
    </section>
  );
}

export function Examples({ onSelect }: { onSelect: (selection: Omit<ExampleSelection, "nonce">) => void }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(false);

  const found = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return PRESETS.filter((preset) => {
      const groupOk = filter === "all" || preset.group === filter;
      const text = `${preset.title} ${preset.description} ${preset.tags} ${preset.type}`.toLowerCase();
      return groupOk && (!normalized || text.includes(normalized));
    });
  }, [filter, query]);

  const showAll = expanded || Boolean(query.trim()) || filter !== "all";
  const displayed = showAll ? found : found.slice(0, 6);

  const select = (id: string) => {
    onSelect({ id, index: 0 });
    document.querySelector("#playground")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <section className="section container examples-section" id="examples" aria-labelledby="examples-heading">
      <div className="examples-top">
        <div>
          <p className="eyebrow">Examples</p>
          <h2 className="section-title" id="examples-heading">
            Small problems
            <br />
            worth automating.
          </h2>
        </div>
        <div className="example-controls">
          <div className="filter-tabs" role="group" aria-label="Example category">
            {(["all", "support", "everyday", "developers"] as const).map((value) => (
              <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)}>
                {value === "all" ? "All" : value[0].toUpperCase() + value.slice(1)}
              </button>
            ))}
          </div>
          <label className="search-field">
            <Search aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} type="search" placeholder="Find a small problem to solve..." aria-label="Search examples" />
          </label>
        </div>
      </div>
      <div className="cases-grid">
        {displayed.map((preset) => (
          <article className="case-card" key={preset.id}>
            <div className="case-top">
              <span className="case-icon">
                <PresetIcon name={preset.icon} />
              </span>
              <span className="case-type">{preset.type[0].toUpperCase() + preset.type.slice(1)}</span>
            </div>
            <h3>{preset.title}</h3>
            <p>{preset.description}</p>
            <div className="case-example">
              <span>{preset.from}</span>
              <ArrowRight aria-hidden="true" />
              <span>{preset.to}</span>
            </div>
            <button className="case-link" type="button" onClick={() => select(preset.id)}>
              Try this example <ArrowUpRight aria-hidden="true" />
            </button>
          </article>
        ))}
      </div>
      {!found.length ? <p className="empty-search">No match yet. Try "review", "support", or "agent".</p> : null}
      <div className="cases-bottom">
        {!showAll && found.length > 6 ? (
          <button className="btn btn-secondary btn-small" type="button" onClick={() => setExpanded(true)}>
            Explore all {found.length} examples <ArrowDown aria-hidden="true" />
          </button>
        ) : null}
        <p aria-live="polite">{found.length ? `Showing ${displayed.length} of ${found.length} examples` : "No matching examples"}</p>
      </div>
    </section>
  );
}
