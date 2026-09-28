import { DEMO_FRAME_ID, DemoFrameBridge } from "./DemoFrameBridge";
import { buildDemoDocument } from "@/lib/demo-document";
import { API_BASE } from "@/lib/playground";
import type { UseCaseDemo as Demo } from "@/lib/use-case-types";

/**
 * Server-rendered section with the sandboxed demo iframe. The document is emitted once as
 * the srcdoc attribute; the client bridge takes no data so nothing is duplicated in the
 * RSC payload. Verified sample results render statically for crawlers and no-JS readers.
 */
export function UseCaseDemo({ demo }: { demo: Demo }) {
  const document = buildDemoDocument(demo, API_BASE);
  return <section className="use-case-demo" id="use-case-demo" aria-labelledby="use-case-demo-title">
    <p className="eyebrow">Interactive demo</p>
    <h2 id="use-case-demo-title">{demo.title}</h2>
    <p>{demo.concept}</p>
    <p className="field-help">{demo.interaction} Each run sends one live request to the public API; results are model judgments and can vary.</p>
    <div className="use-case-demo-frame">
      <iframe id={DEMO_FRAME_ID} title={`Interactive demo: ${demo.title}`} sandbox="allow-scripts" srcDoc={document} referrerPolicy="no-referrer" loading="lazy" />
    </div>
    <DemoFrameBridge />
    <noscript><p>The interactive demo needs JavaScript. The verified sample results below show what it returns.</p></noscript>
    <details className="use-case-demo-samples">
      <summary>Verified sample results <span>({demo.samples.length} inputs, {demo.samples[0]?.response.model})</span></summary>
      <ul>{demo.samples.map((sample, index) => <li key={index}><p>{sample.description}</p><pre><code>{JSON.stringify({ state: sample.request.state, answers: sample.response.answers }, null, 2)}</code></pre></li>)}</ul>
    </details>
  </section>;
}
