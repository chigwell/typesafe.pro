import { API_ENDPOINT, MAX_RESPONSE_BYTES, type EvaluationRequest, type EvaluationResponse } from "../typesafe";
import { API_BASE } from "./config";
import { validateResponse } from "./validation";

export async function readBoundedJson(response: Response): Promise<unknown> {
  const contentType = response.headers.get("Content-Type") || "";
  if (!contentType.includes("application/json") && !contentType.includes("+json")) {
    throw new Error("The gateway returned a non-JSON response.");
  }
  if (!response.body) {
    throw new Error("The gateway returned an empty response.");
  }

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let bytes = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }
      bytes += value.byteLength;
      if (bytes > MAX_RESPONSE_BYTES) {
        await reader.cancel();
        throw new Error("The response is larger than this playground can display (1 MiB).");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const buffer = new Uint8Array(bytes);
  let offset = 0;
  for (const chunk of chunks) {
    buffer.set(chunk, offset);
    offset += chunk.byteLength;
  }

  try {
    return JSON.parse(new TextDecoder().decode(buffer));
  } catch {
    throw new Error("The gateway returned invalid JSON.");
  }
}

export function httpError(response: Response): string {
  const statusCode = response.status;
  if (statusCode === 401 || statusCode === 403) {
    return "This request needs a valid typesafe.pro token. Add your gateway token in Advanced mode, or return to Sample mode.";
  }
  if (statusCode === 429) {
    const header = response.headers.get("Retry-After");
    let seconds = Number(header);
    if (header && !Number.isFinite(seconds)) {
      seconds = Math.ceil((Date.parse(header) - Date.now()) / 1000);
    }
    return header && Number.isFinite(seconds) && seconds > 0 && seconds <= 3600
      ? `The free rate limit was reached. Retry in ${Math.ceil(seconds)} seconds, or explore a sample.`
      : "The free rate limit was reached. Try again later, or explore a sample.";
  }
  if ([502, 503, 504, 529].includes(statusCode)) {
    return `The service is temporarily unavailable (HTTP ${statusCode}). Try again later, or use Sample mode.`;
  }
  if (statusCode === 400 || statusCode === 422) {
    return `The gateway rejected this request (HTTP ${statusCode}). Check the model, state, and questions in Advanced mode.`;
  }
  if (statusCode === 404) {
    return "The API endpoint was not found. Check that the gateway serves /v1/systemone.";
  }
  return `The gateway returned HTTP ${statusCode}. No answer has been substituted. You can still explore the samples.`;
}

export async function runLiveEvaluation(options: {
  request: EvaluationRequest;
  token?: string;
  signal: AbortSignal;
  apiBase?: string;
}): Promise<EvaluationResponse> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options.token) {
    headers.Authorization = `Bearer ${options.token}`;
  }
  const response = await fetch(`${options.apiBase ?? API_BASE}${API_ENDPOINT}`, {
    method: "POST",
    headers,
    body: JSON.stringify(options.request),
    signal: options.signal,
    credentials: "omit",
    mode: "cors",
    cache: "no-store",
    redirect: "error",
    referrerPolicy: "no-referrer",
  });
  if (!response.ok) {
    if (response.body) {
      await response.body.cancel();
    }
    throw new Error(httpError(response));
  }
  return validateResponse(await readBoundedJson(response), options.request);
}
