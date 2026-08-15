/* API client.
   One place that knows about tokens, error shapes, and the SSE wire format. */

const TOKEN_KEY = "bench.token";
const USER_KEY = "bench.user";

export const auth = {
  get token() { return localStorage.getItem(TOKEN_KEY); },
  get username() { return localStorage.getItem(USER_KEY); },
  get signedIn() { return Boolean(this.token); },
  set(token, username) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, username);
  },
  clear() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  },
};

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

/** FastAPI returns errors as {detail: string | [{msg, loc}]}. Flatten both. */
async function readError(response) {
  let detail;
  try {
    const body = await response.json();
    detail = body.detail;
  } catch {
    detail = null;
  }
  if (Array.isArray(detail)) {
    detail = detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
  }
  if (!detail) {
    detail = response.status === 401
      ? "Your session expired. Sign in again."
      : `Request failed (${response.status})`;
  }
  return new ApiError(detail, response.status);
}

async function request(path, { method = "GET", body, form, needsAuth = false } = {}) {
  const headers = {};
  let payload;

  if (form) {
    payload = new URLSearchParams(form);
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (needsAuth) {
    if (!auth.signedIn) throw new ApiError("Sign in first.", 401);
    headers.Authorization = `Bearer ${auth.token}`;
  }

  let response;
  try {
    response = await fetch(path, { method, headers, body: payload });
  } catch {
    throw new ApiError("Can't reach the API. Is the server running?", 0);
  }

  if (response.status === 401 && needsAuth) auth.clear();
  if (!response.ok) throw await readError(response);
  if (response.status === 204) return null;
  return response.json();
}

export const api = {
  health: () => request("/health"),

  register: (username, password) =>
    request("/auth/register", { method: "POST", body: { username, password } }),
  login: (username, password) =>
    request("/auth/login", { method: "POST", form: { username, password } }),

  // ── Developer analytics ────────────────────────────────────────────
  analyze: (username) =>
    request("/analyze", { method: "POST", body: { username }, needsAuth: true }),
  developer: (u) => request(`/developer/${encodeURIComponent(u)}`),
  repositories: (u) => request(`/repositories/${encodeURIComponent(u)}`),
  languages: (u) => request(`/languages/${encodeURIComponent(u)}`),
  activity: (u) => request(`/activity/${encodeURIComponent(u)}`),
  summary: (u) => request(`/summary/${encodeURIComponent(u)}`),
  interview: (u) => request(`/interview/${encodeURIComponent(u)}`),
  score: (u) => request(`/score/${encodeURIComponent(u)}`),
  topProjects: (u) => request(`/top-projects/${encodeURIComponent(u)}`),
  compare: (user1, user2) =>
    request("/compare", { method: "POST", body: { user1, user2 }, needsAuth: true }),

  // ── Repo chat ──────────────────────────────────────────────────────
  indexRepo: (repoUrl, { force = false, wait = false } = {}) =>
    request("/repo-chat/index", {
      method: "POST",
      body: { repo_url: repoUrl, force, wait },
      needsAuth: true,
    }),
  indexStatus: (owner, repo) => request(`/repo-chat/repos/${owner}/${repo}`),
  overview: (owner, repo) => request(`/repo-chat/repos/${owner}/${repo}/overview`),
  createSession: (repoUrl) =>
    request("/repo-chat/sessions", { method: "POST", body: { repo_url: repoUrl }, needsAuth: true }),
  listSessions: () => request("/repo-chat/sessions", { needsAuth: true }),
  transcript: (id) => request(`/repo-chat/sessions/${id}/messages`, { needsAuth: true }),
  deleteSession: (id) =>
    request(`/repo-chat/sessions/${id}`, { method: "DELETE", needsAuth: true }),
  askInSession: (id, question) =>
    request(`/repo-chat/sessions/${id}/messages`, {
      method: "POST",
      body: { question },
      needsAuth: true,
    }),
};

/**
 * Streams an answer over SSE.
 *
 * EventSource can't send an Authorization header, so this reads the response
 * body directly and parses the SSE frames itself.
 */
export async function streamAnswer(sessionId, question, { onCitations, onToken, onDone, onError }) {
  let response;
  try {
    response = await fetch(`/repo-chat/sessions/${sessionId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${auth.token}` },
      body: JSON.stringify({ question }),
    });
  } catch {
    onError?.(new ApiError("Can't reach the API. Is the server running?", 0));
    return;
  }

  if (!response.ok) {
    onError?.(await readError(response));
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      let event = "message";
      const dataLines = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (!dataLines.length) continue;

      let data;
      try {
        data = JSON.parse(dataLines.join("\n"));
      } catch {
        continue;
      }

      if (event === "citations") onCitations?.(data);
      else if (event === "token") onToken?.(data.t);
      else if (event === "done") onDone?.(data);
    }
  }
  onDone?.({});
}
