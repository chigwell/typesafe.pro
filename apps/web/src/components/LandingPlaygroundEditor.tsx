import { ArrowRight, Braces, LoaderCircle, Plus, RotateCcw, SlidersHorizontal, X, type LucideIcon } from "lucide-react";
import { shortCriterion } from "@/lib/playground";
import type { Preset, Question } from "@/lib/typesafe";

type EditorProps = {
  advanced: boolean; mode: "sample" | "live"; currentPreset: Preset; variantIndex: number;
  stateText: string; instructionsText: string; firstQuestion?: Question;
  questionSummary: { icon: LucideIcon; text: string }; jsonText: string; jsonError: string;
  token: string; running: boolean; status: string; statusIsError: boolean;
  onReset: () => void; onVariant: (index: number) => void; onStateChange: (value: string) => void;
  onInstructionsChange: (value: string) => void; onJsonChange: (value: string) => void;
  onFormatJson: () => void; onAddQuestion: (type: Question["type"]) => void;
  onStructuredRules: () => void; onTokenChange: (value: string) => void;
  onToggleAdvanced: () => void; onCancel: () => void; onRun: () => void;
};

export function LandingPlaygroundEditor({
  advanced, mode, currentPreset, variantIndex, stateText, instructionsText, firstQuestion,
  questionSummary, jsonText, jsonError, token, running, status, statusIsError,
  onReset, onVariant, onStateChange, onInstructionsChange, onJsonChange, onFormatJson,
  onAddQuestion, onStructuredRules, onTokenChange, onToggleAdvanced, onCancel, onRun,
}: EditorProps) {
  const QuestionIcon = questionSummary.icon;
  return (
    <div className="editor-panel">
      {!advanced ? (
        <div id="simple-panel">
          <div className="field-heading">
            <label className="field-label" htmlFor="state-input">
              <span className="step-dot">1</span>Your text
            </label>
            <button type="button" className="text-action" onClick={onReset}>
              <RotateCcw aria-hidden="true" /> Reset
            </button>
          </div>
          <textarea
            id="state-input"
            maxLength={20_000}
            spellCheck={false}
            aria-describedby="input-mode-help"
            value={stateText}
            onChange={(event) => onStateChange(event.target.value)}
            placeholder="Paste a message, review, or a few lines of text..."
          />
          <div className="input-footer">
            <div className="variant-buttons" aria-label="Try different sample inputs">
              {currentPreset.variants.map((variant, index) => (
                <button key={variant.name} type="button" className="variant-button" aria-pressed={index === variantIndex} onClick={() => onVariant(index)}>
                  {variant.name}
                </button>
              ))}
            </div>
            <span id="char-count">{stateText.length} chars</span>
          </div>
          <div className="question-field">
            <div className="field-heading">
              <label className="field-label" htmlFor="instructions-input">
                <span className="step-dot">2</span>Your question
              </label>
              <span className="answer-kind">
                <QuestionIcon aria-hidden="true" />
                {questionSummary.text}
              </span>
            </div>
            <textarea id="instructions-input" maxLength={4000} spellCheck={false} value={instructionsText} onChange={(event) => onInstructionsChange(event.target.value)} />
            <AnswerOptions question={firstQuestion} />
          </div>
        </div>
      ) : (
        <div id="advanced-panel">
          <div className="field-heading">
            <label className="field-label" htmlFor="request-json">
              <Braces aria-hidden="true" /> Your request - JSON
            </label>
            <button
              type="button"
              className="text-action"
              onClick={onFormatJson}
            >
              Format JSON
            </button>
          </div>
          <p className="field-help">Edit the text, questions, labels, or scoring rules. Each question sees the same state.</p>
          <div className="advanced-tools">
            <button type="button" onClick={() => onAddQuestion("noul")}>
              <Plus aria-hidden="true" /> Yes / no
            </button>
            <button type="button" onClick={() => onAddQuestion("choice")}>
              <Plus aria-hidden="true" /> Choice
            </button>
            <button type="button" onClick={() => onAddQuestion("score")}>
              <Plus aria-hidden="true" /> Score
            </button>
            <button type="button" onClick={onStructuredRules}>
              <Braces aria-hidden="true" /> Structured rules
            </button>
          </div>
          <textarea id="request-json" spellCheck={false} value={jsonText} onChange={(event) => onJsonChange(event.target.value)} aria-invalid={Boolean(jsonError)} />
          <p className="field-help">Use model, state, and questions. Top-level extras are rejected before a live call.</p>
          {jsonError ? <p id="validation-error">{jsonError}</p> : null}
        </div>
      )}
      {mode === "live" ? (
        <div className="token-field">
          <label htmlFor="api-token">
            typesafe.pro token <span>(optional)</span>
          </label>
          <input id="api-token" type="password" maxLength={2048} autoComplete="off" spellCheck={false} value={token} onChange={(event) => onTokenChange(event.target.value)} placeholder="Only for requests that need a gateway token" />
          <p className="field-help">Kept in this page only, not saved. Never enter a TypeSafe provider key here.</p>
        </div>
      ) : null}
      <div className="editor-actions">
        <button className="advanced-btn" type="button" aria-expanded={advanced} onClick={onToggleAdvanced}>
          <SlidersHorizontal aria-hidden="true" />
          <span>{advanced ? "Simple mode" : "Advanced mode"}</span>
        </button>
        <div className="run-actions">
          {running ? (
            <button className="btn btn-secondary btn-small" type="button" onClick={onCancel}>
              <X aria-hidden="true" /> Cancel
            </button>
          ) : null}
          <button className="btn btn-primary" type="button" disabled={Boolean(jsonError) || running} onClick={onRun}>
            {running ? <LoaderCircle aria-hidden="true" className="spinner" /> : <ArrowRight aria-hidden="true" />}
            {running ? "Asking Jev..." : mode === "sample" ? "Run example" : "Run for free"}
          </button>
        </div>
      </div>
      <p className={`status-line ${statusIsError ? "is-error" : ""}`} id="input-mode-help" aria-live="polite">
        {status}
      </p>
    </div>
  );
}

function AnswerOptions({ question }: { question?: Question }) {
  if (!question) return null;
  const options: string[] =
    question.type === "choice"
      ? Object.keys(question.criteria)
      : question.type === "score"
        ? question.criteria.map((criterion, index) => `${index}: ${shortCriterion(criterion)}`)
        : ["0 = no", "0.5 = unsure", "1 = yes"];
  return (
    <div className="answer-options" aria-label="Possible answers">
      {options.map((option) => (
        <span key={option} className="answer-option">
          {option}
        </span>
      ))}
    </div>
  );
}
