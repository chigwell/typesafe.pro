/**
 * Host runtime injected into every demo iframe before the generated demo script.
 * Plain ES2017 so it runs unbundled inside the sandbox. It is the only path to the API:
 * questions are fixed by the page data; demo code supplies just the state.
 */
export const DEMO_RUNTIME = String.raw`(function () {
  "use strict";
  var config = window.__DEMO || {};
  var questions = Object.freeze(JSON.parse(JSON.stringify(config.questions || {})));
  var samples = Object.freeze((config.samples || []).map(function (sample) {
    return Object.freeze({ state: sample.state, description: sample.description, answers: sample.answers });
  }));
  var endpoint = String(config.apiBase || "https://api.typesafe.pro").replace(/\/+$/, "") + "/v1/systemone";
  var controller = null;
  var listeners = [];
  var theme = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";

  function applyTheme(next) {
    if (next !== "light" && next !== "dark") return;
    theme = next;
    document.documentElement.setAttribute("data-theme", next);
    listeners.forEach(function (callback) { try { callback(next); } catch (error) {} });
  }

  function httpMessage(status, retryAfter) {
    if (status === 429) {
      var seconds = Number(retryAfter);
      if (retryAfter && !isFinite(seconds)) seconds = Math.ceil((Date.parse(retryAfter) - Date.now()) / 1000);
      return isFinite(seconds) && seconds > 0 && seconds <= 3600
        ? "The free rate limit was reached. Retry in " + Math.ceil(seconds) + " seconds."
        : "The free rate limit was reached. Try again in a minute.";
    }
    if (status === 502 || status === 503 || status === 504 || status === 529) return "The service is temporarily unavailable (HTTP " + status + "). Try again later.";
    if (status === 400 || status === 422) return "The gateway rejected this input (HTTP " + status + ").";
    if (status === 401 || status === 403) return "This request needs a valid token.";
    return "The gateway returned HTTP " + status + ".";
  }

  function describeError(error) {
    if (!error) return "Something went wrong.";
    if (error.superseded) return "Replaced by a newer request.";
    if (error.name === "AbortError") return "The request timed out. Try again.";
    // Only a rejected fetch() is a network failure; any other TypeError is a bug in the demo.
    if (error.network) return "The API could not be reached. Check your connection and try again.";
    if (/^(?:TypeError|ReferenceError|RangeError)$/.test(error.name)) {
      if (window.console) console.error(error);
      return "The demo could not display this result.";
    }
    return String(error.message || error);
  }

  function evaluate(state) {
    if (controller) controller.abort();
    var current = new AbortController();
    controller = current;
    var body;
    try {
      body = JSON.stringify({ model: "jev-latest", state: state, questions: questions });
    } catch (error) {
      return Promise.reject(new Error("The input could not be encoded as JSON."));
    }
    if (body.length > 65536) return Promise.reject(new Error("The input is too long for one request."));
    var timer = setTimeout(function () { current.abort(); }, 20000);
    return fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body,
      signal: current.signal,
      credentials: "omit",
      mode: "cors",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer"
    }).catch(function (error) {
      if (error && error.name === "TypeError") error.network = true;
      throw error;
    }).then(function (response) {
      if (!response.ok) {
        var failure = new Error(httpMessage(response.status, response.headers.get("Retry-After")));
        failure.status = response.status;
        throw failure;
      }
      return response.text().then(function (text) {
        if (text.length > 1048576) throw new Error("The response was too large.");
        var data = JSON.parse(text);
        if (!data || typeof data !== "object" || !data.answers || typeof data.answers !== "object") throw new Error("The gateway returned an unexpected response.");
        return data.answers;
      });
    }).catch(function (error) {
      if (error && error.name === "AbortError" && controller !== current) error.superseded = true;
      throw error;
    }).finally(function () {
      clearTimeout(timer);
      if (controller === current) controller = null;
    });
  }

  // Auto-height: measure the content itself (body is height:auto, so its scrollHeight can
  // shrink below the current frame height), coalesce bursts, and stop reporting if the
  // height keeps changing (content sized from the frame, e.g. vh units, would grow forever).
  var lastHeight = 0;
  var scheduled = null;
  var reports = [];
  var frozen = false;
  function measure() {
    var body = document.body;
    var demo = document.getElementById("demo");
    var bottom = demo ? demo.getBoundingClientRect().bottom + window.scrollY : 0;
    return Math.ceil(Math.max(body ? body.scrollHeight : 0, bottom));
  }
  function report() {
    scheduled = null;
    if (frozen) return;
    var height = measure();
    if (Math.abs(height - lastHeight) < 2) return;
    var now = Date.now();
    reports = reports.filter(function (time) { return now - time < 4000; });
    reports.push(now);
    if (reports.length > 40) { frozen = true; return; }
    lastHeight = height;
    window.parent.postMessage({ type: "typesafe-demo:height", height: height }, "*");
  }
  function postHeight() {
    if (scheduled === null) scheduled = setTimeout(report, 32);
  }

  window.addEventListener("message", function (event) {
    if (event.source !== window.parent || !event.data) return;
    if (event.data.type === "typesafe-demo:theme") applyTheme(event.data.value);
    // The host may start listening after the first report (hydration); it asks again.
    if (event.data.type === "typesafe-demo:measure") { lastHeight = 0; frozen = false; reports = []; postHeight(); }
  });
  window.TypeSafeDemo = Object.freeze({
    questions: questions,
    samples: samples,
    evaluate: evaluate,
    describeError: describeError,
    onTheme: function (callback) {
      listeners.push(callback);
      try { callback(theme); } catch (error) {}
    }
  });
  applyTheme(theme);
  function ready() {
    var demo = document.getElementById("demo");
    if (window.ResizeObserver) {
      var sizes = new ResizeObserver(postHeight);
      if (document.body) sizes.observe(document.body);
      if (demo) sizes.observe(demo);
    }
    if (window.MutationObserver && demo) {
      new MutationObserver(postHeight).observe(demo, { childList: true, subtree: true, attributes: true, characterData: true });
    }
    document.addEventListener("transitionend", postHeight, true);
    document.addEventListener("animationend", postHeight, true);
    document.addEventListener("load", postHeight, true);
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(postHeight);
    postHeight();
    window.parent.postMessage({ type: "typesafe-demo:ready" }, "*");
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();
  window.addEventListener("load", postHeight);
})();`;
