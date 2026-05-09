import { API_RETRY_TIMES, API_TIMEOUT_MS, RETRY_BACKOFF_BASE_MS } from "./config";

export type ApiMethod = "GET" | "POST" | "PUT" | "DELETE";

const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "").replace(/\/+$/, "");

const RETRYABLE_STATUS = new Set([408, 429, 500, 502, 503, 504]);

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function buildUrl(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  if (!API_BASE_URL) {
    throw new Error(
      "NEXT_PUBLIC_API_BASE_URL is required before calling API helpers (e.g. https://your-backend-domain.example.com)",
    );
  }
  if (!path.startsWith("/")) {
    throw new Error(`API path must start with '/': ${path}`);
  }
  return `${API_BASE_URL}${path}`;
}

async function parseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

async function fetchWithTimeout(input: RequestInfo | URL, init: RequestInit): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

export async function apiRequest<T>(
  method: ApiMethod,
  path: string,
  options?: { token?: string; body?: unknown; headers?: HeadersInit; retryTimes?: number },
): Promise<T> {
  const retries = options?.retryTimes ?? API_RETRY_TIMES;
  const url = buildUrl(path);
  let lastError: unknown;

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      const headers = new Headers(options?.headers);
      if (options?.body !== undefined && !headers.has("content-type")) {
        headers.set("content-type", "application/json");
      }
      if (options?.token) {
        headers.set("authorization", `Bearer ${options.token}`);
      }

      const response = await fetchWithTimeout(url, {
        method,
        headers,
        body: options?.body !== undefined ? JSON.stringify(options.body) : undefined,
      });

      const body = await parseBody(response);
      if (!response.ok) {
        if (attempt < retries && RETRYABLE_STATUS.has(response.status)) {
          await sleep(RETRY_BACKOFF_BASE_MS * (attempt + 1));
          continue;
        }
        throw new ApiError(`Request failed: ${response.status}`, response.status, body);
      }
      return body as T;
    } catch (error) {
      lastError = error;
      const isLast = attempt >= retries;
      if (!isLast) {
        await sleep(RETRY_BACKOFF_BASE_MS * (attempt + 1));
      }
    }
  }

  throw lastError ?? new Error(`Request failed: ${method} ${url}`);
}

export function apiGet<T>(path: string, token?: string): Promise<T> {
  return apiRequest<T>("GET", path, { token });
}

export function apiPost<T>(path: string, body?: unknown, token?: string): Promise<T> {
  return apiRequest<T>("POST", path, { body, token });
}

export function apiPut<T>(path: string, body?: unknown, token?: string): Promise<T> {
  return apiRequest<T>("PUT", path, { body, token });
}

export function apiDelete<T>(path: string, token?: string): Promise<T> {
  return apiRequest<T>("DELETE", path, { token });
}
