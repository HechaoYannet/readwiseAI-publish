export const DEFAULT_API_TIMEOUT_MS = 15000;
export const DEFAULT_API_RETRY_TIMES = 2;
export const DEFAULT_RESULT_POLL_INTERVAL_MS = 2000;
export const DEFAULT_RESULT_POLL_TIMEOUT_MS = 90000;
export const RETRY_BACKOFF_BASE_MS = 400;

function readNumber(name: string, fallback: number): number {
  const value = process.env[name];
  if (!value) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export const API_TIMEOUT_MS = readNumber("NEXT_PUBLIC_API_TIMEOUT_MS", DEFAULT_API_TIMEOUT_MS);
export const API_RETRY_TIMES = readNumber(
  "NEXT_PUBLIC_API_RETRY_TIMES",
  DEFAULT_API_RETRY_TIMES,
);
export const RESULT_POLL_INTERVAL_MS = readNumber(
  "NEXT_PUBLIC_RESULT_POLL_INTERVAL_MS",
  DEFAULT_RESULT_POLL_INTERVAL_MS,
);
export const RESULT_POLL_TIMEOUT_MS = readNumber(
  "NEXT_PUBLIC_RESULT_POLL_TIMEOUT_MS",
  DEFAULT_RESULT_POLL_TIMEOUT_MS,
);

