// Compatibility facade: callers keep their existing imports while responsibilities stay separate.
export { API_BASE } from "./playground/config";
export { clone, isRecord, isJsonRecord, isProbability, canonical, simpleCompatible, shortCriterion } from "./playground/shared";
export { requestFor, findSample, answerForSample } from "./playground/samples";
export { validateRequest, validateResponse } from "./playground/validation";
export { readBoundedJson, httpError, runLiveEvaluation } from "./playground/transport";
