"use client";

import { useEffect, useRef, useState } from "react";
import { Copy } from "lucide-react";
import { copyText } from "@/lib/clipboard";
import { LANGUAGE_ORDER, LANGUAGES, makeCode, type LanguageId } from "@/lib/codegen";
import { runLiveEvaluation, validateRequest } from "@/lib/playground";
import { highlightCode } from "@/lib/syntax";
import { LIVE_TIMEOUT_MS, type EvaluationResponse } from "@/lib/typesafe";
import type { UseCaseExample } from "@/lib/use-case-types";
import { ResultPanel } from "./Playground";

export function UseCasePlayground({ examples }: { examples: UseCaseExample[] }) {
  const [index, setIndex] = useState(0);
  const example = examples[index];
  const [json, setJson] = useState(() => JSON.stringify(example.request, null, 2));
  const [language, setLanguage] = useState<LanguageId>("python");
  const [result, setResult] = useState<EvaluationResponse | null>(example.response);
  const [resultRequest, setResultRequest] = useState(example.request);
  const [live, setLive] = useState(false);
  const [running, setRunning] = useState(false);
  const [raw, setRaw] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState(false);
  const active = useRef<AbortController | null>(null);
  let request = example.request;
  let validationError = "";
  try { request = validateRequest(JSON.parse(json)); }
  catch (failure) { validationError = failure instanceof Error ? failure.message : "Invalid request JSON."; }
  const code = validationError ? `${LANGUAGES[language].comment} Fix the request JSON to generate code.` : makeCode(language, request);

  useEffect(() => () => active.current?.abort(), []);

  function cancel() {
    active.current?.abort();
    active.current = null;
    setRunning(false);
  }

  function select(next: number) {
    cancel();
    setIndex(next);
    setJson(JSON.stringify(examples[next].request, null, 2));
    setResult(examples[next].response);
    setResultRequest(examples[next].request);
    setLive(false);
    setStatus("");
    setError(false);
  }

  async function run() {
    if (validationError || running) return;
    const sent = request;
    const controller = new AbortController();
    active.current = controller;
    const timer = window.setTimeout(() => controller.abort("timeout"), LIVE_TIMEOUT_MS);
    setRunning(true);
    setResult(null);
    setError(false);
    setStatus("Sending your request to typesafe.pro and TypeSafe…");
    try {
      const response = await runLiveEvaluation({ request: sent, signal: controller.signal });
      if (active.current !== controller) return;
      setResult(response);
      setResultRequest(sent);
      setLive(true);
      setStatus("Live response received. Probabilities may differ from the previous verification.");
    } catch (failure) {
      if (active.current !== controller) return;
      setError(true);
      setStatus(controller.signal.reason === "timeout" ? "The request timed out after 20 seconds. Try again." : failure instanceof Error ? failure.message : "Request failed.");
    } finally {
      window.clearTimeout(timer);
      if (active.current === controller) {
        active.current = null;
        setRunning(false);
      }
    }
  }

  async function copy(value: string) {
    setStatus(await copyText(value) ? "Copied to clipboard." : "Copy failed. Select the text to copy it.");
  }

  return (
    <section className="use-case-interactive" id="playground" aria-labelledby="try-heading">
      <h2 id="try-heading">Try online</h2>
      <p>Start with a verified example, edit the request, then ask Jev. A live request is sent only when you press Try online.</p>
      <div className="variant-buttons use-case-example-tabs" role="group" aria-label="Example inputs">
        {examples.map((item, itemIndex) => <button className="variant-button" type="button" key={item.kind} aria-pressed={index === itemIndex} onClick={() => select(itemIndex)}>{item.name}</button>)}
      </div>
      <p><strong>Expected behavior:</strong> {example.expected_description}</p>
      <div className="playground">
        <div className="pg-grid">
          <div className="editor-panel">
            <label className="field-label" htmlFor="use-case-request">Request JSON</label>
            <textarea id="use-case-request" className="use-case-request" spellCheck={false} value={json} aria-invalid={Boolean(validationError)} aria-describedby="use-case-status" onChange={(event) => {
              cancel(); setJson(event.target.value); setResult(null); setLive(false); setStatus("Request changed. Run it to see a new answer."); setError(false);
            }} />
            <div className="editor-actions">
              <button type="button" className="text-action" onClick={() => select(index)}>Reset example</button>
              {running ? <button type="button" className="btn btn-secondary" onClick={() => { cancel(); setStatus("Request cancelled."); }}>Cancel</button> : null}
              <button className="btn btn-primary" type="button" disabled={Boolean(validationError) || running} onClick={run}>{running ? "Asking Jev…" : "Try online"}</button>
            </div>
            <p className={`status-line ${validationError || error ? "is-error" : ""}`} id="use-case-status" role="status">{validationError || status}</p>
            <p className="field-help">Use non-sensitive test data. Live input goes to typesafe.pro and TypeSafe. Anonymous requests use the gateway’s free rate limit.</p>
          </div>
          <ResultPanel result={result} request={resultRequest} badge={live ? "Live response" : "Previous verification"} live={live} rawVisible={raw} nextStep={example.expected_description} meta={live ? result?.model ?? "" : `${example.response.model} · verified ${example.verified_at.slice(0, 10)} · new probabilities may differ`} running={running} onToggleRaw={() => setRaw((value) => !value)} onCopyResult={() => { if (result) void copy(JSON.stringify(result, null, 2)); }} />
        </div>
      </div>
      <div className="code-shell use-case-code" id="developers">
        <div className="code-heading"><span>The current request, in code</span><button className="copy-code" type="button" disabled={Boolean(validationError)} onClick={() => copy(code)}><Copy aria-hidden="true" /> Copy</button></div>
        <div className="code-tabs" role="tablist" aria-label="Programming language" onKeyDown={(event) => {
          if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
          event.preventDefault();
          const current = LANGUAGE_ORDER.indexOf(language);
          const next = event.key === "Home" ? 0 : event.key === "End" ? LANGUAGE_ORDER.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + LANGUAGE_ORDER.length) % LANGUAGE_ORDER.length;
          setLanguage(LANGUAGE_ORDER[next]);
          document.getElementById(`uc-tab-${LANGUAGE_ORDER[next]}`)?.focus();
        }}>
          {LANGUAGE_ORDER.map((item) => <button key={item} id={`uc-tab-${item}`} className="code-tab" role="tab" type="button" tabIndex={item === language ? 0 : -1} aria-selected={item === language} aria-controls="uc-code-panel" onClick={() => setLanguage(item)}>{LANGUAGES[item].label}</button>)}
        </div>
        <div className="code-body" id="uc-code-panel" role="tabpanel" aria-labelledby={`uc-tab-${language}`}>
          <pre className="code-pre" tabIndex={0} aria-label="Code example"><code>{highlightCode(code, language).map((line, lineIndex) => <span className="code-line" key={lineIndex}><span className="line-number" aria-hidden="true">{lineIndex + 1}</span><span className="code-line-content">{line.map((token, tokenIndex) => <span className={`token-${token.kind}`} key={tokenIndex}>{token.text}</span>)}</span></span>)}</code></pre>
        </div>
        <div className="code-footer"><span>{LANGUAGES[language].filename}</span><span>Anonymous HTTP</span></div>
      </div>
    </section>
  );
}
