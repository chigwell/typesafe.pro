"use client";

import { useCallback, useMemo, useState } from "react";
import { PRESETS } from "@/lib/presets";
import { requestFor } from "@/lib/playground";
import type { EvaluationRequest } from "@/lib/typesafe";
import { DeveloperSection } from "./DeveloperSection";
import { Examples, Primitives } from "./Examples";
import { FAQ } from "./FAQ";
import { FinalCta, Footer } from "./Footer";
import { Header } from "./Header";
import { Hero } from "./Hero";
import { type ExampleSelection, Playground } from "./Playground";

export function LandingPage() {
  const initialRequest = useMemo(() => requestFor(PRESETS[0], 0), []);
  const [selection, setSelection] = useState<ExampleSelection>({ id: PRESETS[0].id, index: 0, nonce: 0 });
  const [developerRequest, setDeveloperRequest] = useState<EvaluationRequest>(initialRequest);
  const [developerValid, setDeveloperValid] = useState(true);
  const [toast, setToast] = useState("");

  const onRequestChange = useCallback((request: EvaluationRequest, valid: boolean) => {
    setDeveloperRequest(request);
    setDeveloperValid(valid);
  }, []);

  const showToast = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast((current) => (current === message ? "" : current)), 2800);
  }, []);

  return (
    <>
      <a className="skip-link" href="#playground">
        Skip to playground
      </a>
      <Header />
      <main id="top">
        <Hero />
        <Playground selection={selection} onRequestChange={onRequestChange} onToast={showToast} />
        <Primitives />
        <Examples
          onSelect={({ id, index }) =>
            setSelection((current) => ({
              id,
              index,
              nonce: current.nonce + 1,
            }))
          }
        />
        <DeveloperSection request={developerRequest} valid={developerValid} onToast={showToast} />
        <FAQ />
        <FinalCta />
      </main>
      <Footer />
      <div className={`toast ${toast ? "is-visible" : ""}`} role="status" aria-live="polite">
        {toast}
      </div>
    </>
  );
}

