// Thin fetch wrapper: JSON, CSRF header, translated server errors.

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function csrfToken(): string | undefined {
  const match = document.cookie.match(/(?:^|; )kp_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : undefined;
}

type Query = Record<string, string | number | boolean | null | undefined | string[]>;

function withQuery(url: string, query?: Query): string {
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => params.append(k, x));
    else params.append(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}${url.includes("?") ? "&" : "?"}${qs}` : url;
}

export async function request<T = any>(
  method: string,
  url: string,
  body?: unknown,
  opts: { query?: Query; headers?: Record<string, string>; raw?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...(opts.headers || {}) };
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (method !== "GET") {
    const csrf = csrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }
  const res = await fetch(withQuery(url, opts.query), { method, headers, body: payload, credentials: "same-origin" });
  if (opts.raw) {
    if (!res.ok) throw new ApiError(res.status, "errors.http", res.statusText);
    return res as unknown as T;
  }
  const text = await res.text();
  const data = text ? safeJson(text) : null;
  if (!res.ok) {
    const err = data?.error;
    throw new ApiError(res.status, err?.code ?? "errors.http", err?.message ?? res.statusText, err?.details);
  }
  return data as T;
}

function safeJson(text: string): any {
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

export const api = {
  get: <T = any>(url: string, query?: Query) => request<T>("GET", url, undefined, { query }),
  post: <T = any>(url: string, body?: unknown, query?: Query) => request<T>("POST", url, body, { query }),
  put: <T = any>(url: string, body?: unknown) => request<T>("PUT", url, body),
  patch: <T = any>(url: string, body?: unknown) => request<T>("PATCH", url, body),
  del: <T = any>(url: string) => request<T>("DELETE", url),
  upload: <T = any>(url: string, form: FormData) => request<T>("POST", url, form),
};
