type EditorProps = {
  json: string; validationError: string; running: boolean; error: boolean; status: string;
  onChange: (value: string) => void; onReset: () => void; onCancel: () => void; onRun: () => void;
};

export function UseCaseRequestEditor({ json, validationError, running, error, status, onChange, onReset, onCancel, onRun }: EditorProps) {
  return (
    <div className="editor-panel">
      <label className="field-label" htmlFor="use-case-request">Request JSON</label>
      <textarea id="use-case-request" className="use-case-request" spellCheck={false} value={json} aria-invalid={Boolean(validationError)} aria-describedby="use-case-status" onChange={(event) => onChange(event.target.value)} />
      <div className="editor-actions">
        <button type="button" className="text-action" onClick={onReset}>Reset example</button>
        {running ? <button type="button" className="btn btn-secondary" onClick={onCancel}>Cancel</button> : null}
        <button className="btn btn-primary" type="button" disabled={Boolean(validationError) || running} onClick={onRun}>{running ? "Asking Jev…" : "Try online"}</button>
      </div>
      <p className={`status-line ${validationError || error ? "is-error" : ""}`} id="use-case-status" role="status">{validationError || status}</p>
      <p className="field-help">Use non-sensitive test data. Live input goes to typesafe.pro and TypeSafe. Anonymous requests use the gateway’s free rate limit.</p>
    </div>
  );
}
