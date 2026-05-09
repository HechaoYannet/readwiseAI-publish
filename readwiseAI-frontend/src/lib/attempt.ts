import { apiGet, apiPost } from "./api";
import { RESULT_POLL_INTERVAL_MS, RESULT_POLL_TIMEOUT_MS } from "./config";

export type AttemptSubmitResponse = {
  request_id: string;
  session_id: string;
  status: "processing";
  result_url: string;
};

export type AttemptResultResponse = {
  request_id: string;
  status: "processing" | "completed" | "failed" | "not_found";
  session_id?: string;
  results?: Record<string, unknown>;
  error_log?: string[];
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function submitAttempt(
  payload: Record<string, unknown>,
  token: string,
): Promise<AttemptSubmitResponse> {
  return apiPost<AttemptSubmitResponse>("/api/attempt", payload, token);
}

export async function pollAttemptResult(
  requestId: string,
  token: string,
  options?: { intervalMs?: number; timeoutMs?: number },
): Promise<AttemptResultResponse> {
  const intervalMs = options?.intervalMs ?? RESULT_POLL_INTERVAL_MS;
  const timeoutMs = options?.timeoutMs ?? RESULT_POLL_TIMEOUT_MS;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    const result = await apiGet<AttemptResultResponse>(`/api/result/${requestId}`, token);
    if (result.status !== "processing") return result;
    await sleep(intervalMs);
  }

  throw new Error(
    `Polling timeout for request_id=${requestId}: /api/result/${requestId} did not finish within ${timeoutMs}ms`,
  );
}
