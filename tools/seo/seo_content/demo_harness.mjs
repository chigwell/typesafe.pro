// Runs generated demo code in jsdom against the verified sample answers and reports every
// error the demo hits. Usage: node --permission ... demo_harness.mjs <jsdom path> < input.json
// Input: {html, js, questions, samples: [{state, description, answers}]}.
// Output: {errors: [string]} on stdout. The caller runs this with Node's permission model
// and an empty environment: the code under test is model-written and not trusted.
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { JSDOM, VirtualConsole } = require(process.argv[2]);

const input = JSON.parse(await new Promise((done) => {
  let text = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => (text += chunk));
  process.stdin.on("end", () => done(text));
}));

const errors = [];
let current = "";
const describe = (error) => {
  if (!error) return String(error);
  // Demo frames look like "at showVisual (eval at run (file:…), <anonymous>:33:26)".
  const frame = String(error.stack || "").split("\n").find((line) => line.includes("<anonymous>:"));
  const match = frame && /at (?:(\S+) \()?.*<anonymous>:(\d+):\d+/.exec(frame);
  const where = match ? ` (demo js line ${match[2]}${match[1] && match[1] !== "eval" ? `, in ${match[1]}` : ""})` : "";
  return `${error.name || "Error"}: ${error.message || error}${where}`;
};
process.on("unhandledRejection", (reason) => errors.push(`${current}: unhandled rejection ${describe(reason)}`));

const settle = async () => {
  for (let tick = 0; tick < 12; tick += 1) await new Promise((done) => setTimeout(done, 25));
};

/** Browser APIs a demo may reasonably use that jsdom lacks; no-ops, not failures. */
function polyfill(window) {
  window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
  window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
  window.IntersectionObserver = class { observe() {} unobserve() {} disconnect() {} };
  window.Element.prototype.scrollIntoView = function () {};
  window.Element.prototype.animate = function () {
    return { finished: window.Promise.resolve(), cancel() {}, finish() {}, play() {}, pause() {}, onfinish: null };
  };
  const context = new Proxy({}, { get: (target, key) => (key in target ? target[key] : () => context), set: (target, key, value) => ((target[key] = value), true) });
  window.HTMLCanvasElement.prototype.getContext = () => context;
}

async function run(label, answersFor, sampleIndex) {
  current = label;
  const virtualConsole = new VirtualConsole();
  virtualConsole.on("jsdomError", (error) => {
    if (!/Not implemented/.test(error.message)) errors.push(`${label}: ${describe(error.detail || error)}`);
  });
  virtualConsole.on("error", (...args) => errors.push(`${label}: console.error ${args.map(String).join(" ").slice(0, 200)}`));
  const dom = new JSDOM(`<!doctype html><html><body><div id="demo">${input.html}</div></body></html>`, {
    runScripts: "outside-only",
    pretendToBeVisual: true,
    virtualConsole,
  });
  const window = dom.window;
  polyfill(window);
  window.addEventListener("error", (event) => errors.push(`${label}: ${describe(event.error || event)}`));
  const copy = (value) => window.JSON.parse(JSON.stringify(value));
  const calls = [];
  const described = [];
  window.TypeSafeDemo = window.Object.freeze({
    questions: window.Object.freeze(copy(input.questions)),
    samples: window.Object.freeze(input.samples.map((sample) => window.Object.freeze(copy({ state: sample.state, description: sample.description, answers: sample.answers })))),
    evaluate(state) {
      calls.push(state);
      return answersFor(window, copy);
    },
    describeError(error) {
      described.push(error);
      return "Something went wrong.";
    },
    onTheme(callback) {
      callback("light");
    },
  });
  try {
    window.eval(input.js);
  } catch (error) {
    errors.push(`${label}: the script throws on load: ${describe(error)}`);
    window.close();
    return { calls, described };
  }
  await settle();

  const document = window.document;
  const chip = [...document.querySelectorAll("[data-sample]")].find((element) => element.getAttribute("data-sample") === String(sampleIndex));
  if (chip) {
    chip.click();
    await settle();
  }
  const sample = input.samples[sampleIndex];
  const texts = typeof sample.state === "string" ? [sample.state] : Object.values(sample.state).filter((value) => typeof value === "string");
  let next = 0;
  for (const field of document.querySelectorAll("input:not([type=checkbox]):not([type=radio]):not([type=range]), textarea")) {
    if (!field.value) field.value = texts[next++ % Math.max(texts.length, 1)] ?? "Sample input";
    field.dispatchEvent(new window.Event("input", { bubbles: true }));
  }
  for (const select of document.querySelectorAll("select")) {
    if (select.value) continue;
    const options = [...select.options].filter((option) => option.value);
    const match = options.find((option) => texts.includes(option.value) || texts.includes(option.textContent.trim())) ?? options[0];
    if (match) select.value = match.value;
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
  }
  const buttons = [...document.querySelectorAll("button")].filter((button) => !button.hasAttribute("data-sample") && !button.classList.contains("ts-chip"));
  const main = buttons.find((button) => button.classList.contains("ts-btn")) ?? buttons[0];
  if (!main) {
    errors.push(`${label}: no main button (a <button class="ts-btn">) to press`);
  } else {
    main.click();
    await settle();
  }
  window.close();
  return { calls, described };
}

for (let index = 0; index < input.samples.length; index += 1) {
  const sample = input.samples[index];
  const label = `sample ${index + 1} ("${String(sample.description).slice(0, 60)}")`;
  const { calls, described } = await run(label, (window, copy) => window.Promise.resolve(copy(sample.answers)), index);
  if (!calls.length) errors.push(`${label}: pressing the main button with the sample input did not call TypeSafeDemo.evaluate`);
  // evaluate() resolved with real answers, so any error the demo reports is its own bug.
  for (const error of described) errors.push(`${label}: rendering the verified answers failed with ${describe(error)}`);
}

// A failing request must be reported in the status element, not break the demo.
await run("failed request", (window) => {
  const failure = new window.Error("The free rate limit was reached. Try again in a minute.");
  failure.status = 429;
  return window.Promise.reject(failure);
}, 0);

process.stdout.write(JSON.stringify({ errors: [...new Set(errors)].slice(0, 12) }));
