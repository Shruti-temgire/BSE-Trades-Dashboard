// Thin wrappers around the REST API. All URLs are relative; Vite proxies them to FastAPI.

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { headers: { Accept: 'application/json' }, ...options });
  } catch {
    throw new ApiError('Cannot reach the API server. Is the backend running on port 8000?', 0, null);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof body?.detail === 'string' ? body.detail : `Request failed (HTTP ${response.status})`;
    throw new ApiError(detail, response.status, body);
  }
  return body;
}

const qs = (params) => new URLSearchParams(params).toString();

export const api = {
  dashboard: ({ page, pageSize, search }) =>
    request(`/api/dashboard?${qs({ page, page_size: pageSize, search })}`),
  trades: ({ page, pageSize, search }) =>
    request(`/api/trades?${qs({ page, page_size: pageSize, search })}`),
  startPull: () => request('/api/pulls', { method: 'POST' }),
};

export const streamUrl = (since) => `/api/stream?since=${since}`;
