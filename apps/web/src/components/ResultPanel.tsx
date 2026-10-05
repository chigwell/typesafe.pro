"use client";

import { ArrowRight, Check, Code2, Copy, Layers, LoaderCircle } from "lucide-react";
import type { EvaluationRequest, EvaluationResponse, Question } from "@/lib/typesafe";

export function ResultPanel({
  result,
  request,
  badge,
  live,
  rawVisible,
  nextStep,
  meta,
  running,
  onToggleRaw,
  onCopyResult,
}: {
  result: EvaluationResponse | null;
  request: EvaluationRequest;
  badge: string;
  live: boolean;
  rawVisible: boolean;
  nextStep: string;
  meta: string;
  running: boolean;
  onToggleRaw: () => void;
  onCopyResult: () => void;
}) {
  return (
    <div className="result-panel" aria-busy={running}>
      <div className="result-heading">
        <div className="field-label">
          <span className="step-dot">3</span>Answer
        </div>
        <span className={`badge ${live ? "is-live" : ""}`}>
          <span className="dot" aria-hidden="true" />
          {badge}
        </span>
      </div>
      {result ? (
        <>
          {rawVisible ? (
            <pre className="raw-result">{JSON.stringify(result, null, 2)}</pre>
          ) : (
            <div className="result-main">
              {Object.entries(request.questions).map(([id, question]) => (
                <AnswerView key={id} id={id} question={question} answer={result.answers[id]} multiple={Object.keys(request.questions).length > 1} />
              ))}
            </div>
          )}
          <div className="result-bottom">
            <div className="next-step">
              <ArrowRight aria-hidden="true" />
              <div>
                <p className="next-step-label">Next step</p>
                <p className="next-step-text">{nextStep}</p>
              </div>
            </div>
            <div className="result-links">
              <button type="button" onClick={onToggleRaw}>
                <Code2 aria-hidden="true" />
                {rawVisible ? "Visual answer" : "View JSON"}
              </button>
              <button type="button" onClick={onCopyResult}>
                <Copy aria-hidden="true" />
                Copy result
              </button>
            </div>
            <p className="result-meta">{meta}</p>
          </div>
        </>
      ) : (
        <div className="empty-result">
          {running ? <LoaderCircle aria-hidden="true" className="spinner" /> : <Layers aria-hidden="true" />}
          <h3>{running ? "Asking Jev..." : "Ready when you are."}</h3>
          <p>{running ? "Sending your text and questions to the live gateway." : "Run an unchanged sample, or switch to Live API to try your own input."}</p>
        </div>
      )}
    </div>
  );
}

function AnswerView({ id, question, answer, multiple }: { id: string; question: Question; answer: EvaluationResponse["answers"][string]; multiple: boolean }) {
  if (!answer) return null;
  const pretitles = {
    choice: "The best-fitting label",
    score: "A position on your scale",
    noul: "Probability that the answer is yes",
  };
  return (
    <div className={multiple ? "multi-answer" : ""}>
      <p className="result-pretitle">{multiple ? id : pretitles[answer.type]}</p>
      {answer.type === "choice" ? (
        <>
          <div className="result-value">
            {answer.choice}
            <Check aria-hidden="true" />
          </div>
          <ProbabilityRows distribution={answer.probabilities} selected={answer.choice} question={question} />
          <ConfidenceLine confidence={answer.confidence} kind="choice" />
        </>
      ) : answer.type === "score" ? (
        <>
          <div className="result-value">
            {Number(answer.score.toFixed(2)).toString()}
            <span className="unit">/ {question.type === "score" ? question.criteria.length - 1 : 1}</span>
          </div>
          <ProbabilityRows
            distribution={answer.probabilities}
            selected={Object.entries(answer.probabilities).reduce((best, entry) => (entry[1] > best[1] ? entry : best))[0]}
            question={question}
          />
          <ConfidenceLine confidence={answer.confidence} kind="score" />
        </>
      ) : (
        <>
          <div className="result-value">
            {Math.round(answer.noul * 100)}% <span className="unit">yes</span>
          </div>
          <ProbabilityRows distribution={{ yes: answer.noul, no: 1 - answer.noul }} selected={answer.noul >= 0.5 ? "yes" : "no"} question={question} />
          <p className="result-explanation">Near 1 is a strong yes. Near 0 is a strong no. Around 0.5 means uncertainty. Noul has no separate confidence value.</p>
        </>
      )}
    </div>
  );
}

function ProbabilityRows({ distribution, selected, question }: { distribution: Record<string, number>; selected: string; question: Question }) {
  return (
    <div className="probabilities">
      {Object.entries(distribution).map(([label, probability]) => (
        <div key={label} className={`prob-row ${label === selected ? "winning" : ""}`}>
          <span className="prob-label">{question.type === "score" ? `Level ${label}` : label}</span>
          <span className="prob-track" aria-hidden="true">
            <span className="prob-fill" style={{ width: `${Math.max(0, Math.min(100, probability * 100))}%` }} />
          </span>
          <span className="prob-number">{Math.round(probability * 100)}%</span>
        </div>
      ))}
    </div>
  );
}

function ConfidenceLine({ confidence, kind }: { confidence: number; kind: "choice" | "score" }) {
  return (
    <>
      <div className="confidence-line">
        <span>Model confidence</span>
        <strong>{confidence.toFixed(2)}</strong>
      </div>
      <p className="result-explanation">
        {kind === "score"
          ? "The score can fall between levels. Confidence describes how concentrated the answer is, not whether it is correct."
          : "Probabilities compare your labels. Confidence describes how decisive the model is, not whether it is correct."}
      </p>
    </>
  );
}
