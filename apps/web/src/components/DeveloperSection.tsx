"use client";

import { ArrowUpRight, Check, Code2, Copy } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { copyText } from "@/lib/clipboard";
import { LANGUAGE_ORDER, LANGUAGES, makeCode, type LanguageId } from "@/lib/codegen";
import { API_BASE } from "@/lib/playground";
import { highlightCode } from "@/lib/syntax";
import type { EvaluationRequest } from "@/lib/typesafe";

const LANGUAGE_MARKS: Record<LanguageId, { label: string; className: string }> = {
  python: { label: "Py", className: "python" },
  javascript: { label: "JS", className: "javascript" },
  typescript: { label: "TS", className: "typescript" },
  curl: { label: "$", className: "curl" },
  go: { label: "Go", className: "go" },
  php: { label: "php", className: "php" },
  java: { label: "Ja", className: "java" },
};

export function DeveloperSection({
  request,
  valid,
  onToast,
}: {
  request: EvaluationRequest;
  valid: boolean;
  onToast: (message: string) => void;
}) {
  const [language, setLanguage] = useState<LanguageId>("python");
  const code = useMemo(
    () => (valid ? makeCode(language, request) : `${LANGUAGES[language].comment} Fix the request JSON to generate a matching example.`),
    [language, request, valid],
  );
  const { displayCode, typing } = useTypingCode(code);
  const highlightedLines = useMemo(() => highlightCode(displayCode, language), [displayCode, language]);
  const preRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    if (preRef.current) {
      preRef.current.scrollTop = 0;
      preRef.current.scrollLeft = 0;
    }
  }, [code]);

  return (
    <section className="section container" id="developers" aria-labelledby="developers-heading">
      <div className="developer-layout">
        <div className="developer-intro">
          <p className="eyebrow">From "oh, I get it" to your app</p>
          <h2 className="section-title" id="developers-heading">
            Now put it
            <br />
            in your app.
          </h2>
          <p className="section-copy">
            The same example you just tried.
            <br />
            In a language you already use.
          </p>
          <p className="endpoint-label">YOUR API BASE URL</p>
          <div className="endpoint">
            <code>{API_BASE}</code>
            <button
              className="icon-btn"
              type="button"
              aria-label="Copy API base URL"
              title="Copy API base URL"
              onClick={async () => {
                if (await copyText(API_BASE)) onToast("API base URL copied");
              }}
            >
              <Copy aria-hidden="true" />
            </button>
          </div>
          <div className="developer-notes">
            <p>
              <Check aria-hidden="true" /> Anonymous HTTP examples; no key required by this gateway.
            </p>
            <p>
              <Check aria-hidden="true" /> One request. Named, typed answers.
            </p>
            <p>
              <Check aria-hidden="true" /> Change the playground. The code follows.
            </p>
          </div>
          <a className="developer-docs" href="https://docs.typesafe.ai/api" target="_blank" rel="noopener noreferrer">
            Read the upstream API reference <ArrowUpRight aria-hidden="true" />
          </a>
        </div>
        <div className="code-shell">
          <div className="code-heading">
            <span>
              <Code2 aria-hidden="true" />
              Your playground, in code
            </span>
            <button
              type="button"
              className="copy-code"
              disabled={!valid}
              onClick={async () => {
                if (await copyText(code)) onToast("Complete code copied");
              }}
            >
              <Copy aria-hidden="true" />
              <span>Copy</span>
            </button>
          </div>
          <div className="code-tabs" role="tablist" aria-label="Programming language">
            {LANGUAGE_ORDER.map((item) => (
              <button
                key={item}
                className="code-tab"
                type="button"
                role="tab"
                id={`code-tab-${item}`}
                aria-selected={language === item}
                aria-controls="code-panel"
                tabIndex={language === item ? 0 : -1}
                onClick={() => setLanguage(item)}
              >
                <LanguageLogo language={item} />
                {LANGUAGES[item].label}
              </button>
            ))}
          </div>
          <div className="code-body" id="code-panel" role="tabpanel" aria-labelledby={`code-tab-${language}`}>
            <pre className="code-pre" tabIndex={0} aria-label="Code example" ref={preRef}>
              <code>
                {highlightedLines.map((line, lineIndex) => (
                  <span className="code-line" key={`${lineIndex}-${line.map((token) => token.text).join("")}`}>
                    <span className="line-number" aria-hidden="true">
                      {lineIndex + 1}
                    </span>
                    <span className="code-line-content">
                      {line.map((token, tokenIndex) => (
                        <span className={`token-${token.kind}`} key={`${tokenIndex}-${token.text}`}>
                          {token.text}
                        </span>
                      ))}
                      {typing && lineIndex === highlightedLines.length - 1 ? <span className="typing-cursor" aria-hidden="true" /> : null}
                    </span>
                  </span>
                ))}
              </code>
            </pre>
          </div>
          <div className="code-footer">
            <span>{LANGUAGES[language].filename}</span>
            <span>
              <span className="dot" aria-hidden="true" />
              Anonymous HTTP
            </span>
          </div>
        </div>
      </div>
      <details className="sdk-details">
        <summary>Already using a TypeSafe SDK? Change the API root.</summary>
        <p>
          The official SDKs require a key. Use your own typesafe.pro gateway token, stored server-side in <code>TYPESAFE_PRO_API_KEY</code>. For keyless requests, use the HTTP examples above. Do not use an upstream provider key.
        </p>
      </details>
    </section>
  );
}

function LanguageLogo({ language }: { language: LanguageId }) {
  const mark = LANGUAGE_MARKS[language];
  return (
    <span className={`language-logo logo-${mark.className}`} aria-hidden="true">
      {mark.label}
    </span>
  );
}

function useTypingCode(code: string) {
  const [displayLength, setDisplayLength] = useState(code.length);
  const [typing, setTyping] = useState(false);

  useEffect(() => {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion || code.length < 80) {
      setDisplayLength(code.length);
      setTyping(false);
      return;
    }

    let frame = 0;
    let lastFrame = 0;
    const started = performance.now();
    const duration = Math.min(1350, Math.max(520, code.length * 0.58));

    setDisplayLength(0);
    setTyping(true);

    const tick = (now: number) => {
      if (now - lastFrame < 28) {
        frame = requestAnimationFrame(tick);
        return;
      }
      lastFrame = now;
      const progress = Math.min(1, (now - started) / duration);
      const nextLength = Math.floor(code.length * progress);
      setDisplayLength(nextLength);
      if (progress < 1) {
        frame = requestAnimationFrame(tick);
      } else {
        setDisplayLength(code.length);
        setTyping(false);
      }
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [code]);

  return {
    displayCode: code.slice(0, displayLength),
    typing,
  };
}
