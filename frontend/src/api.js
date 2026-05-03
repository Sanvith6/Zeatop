const AUTH_STORAGE_KEY = "imsAccessToken";
const DEMO_USERNAME = import.meta.env.VITE_DEMO_USERNAME || "sre-intern";
const DEMO_PASSWORD = import.meta.env.VITE_DEMO_PASSWORD || "zeotap-local";

async function getAccessToken() {
  const cached = sessionStorage.getItem(AUTH_STORAGE_KEY);
  if (cached) {
    return cached;
  }
  const response = await fetch("/api/auth/token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: DEMO_USERNAME, password: DEMO_PASSWORD })
  });
  if (!response.ok) {
    throw new Error("Unable to authenticate dashboard session");
  }
  const body = await response.json();
  sessionStorage.setItem(AUTH_STORAGE_KEY, body.access_token);
  return body.access_token;
}

export async function apiFetch(path, options = {}) {
  const token = await getAccessToken();
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(options.headers || {}) },
    ...options
  });
  if (response.status === 401) {
    sessionStorage.removeItem(AUTH_STORAGE_KEY);
  }
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // Keep HTTP status text when the response is not JSON.
    }
    throw new Error(message);
  }
  return response.json();
}

export const getWorkItems = (status) => apiFetch(`/api/workitems${status ? `?status=${status}` : ""}`);
export const getWorkItem = (id) => apiFetch(`/api/workitems/${id}`);
export const transitionWorkItem = (id, newState) =>
  apiFetch(`/api/workitems/${id}/transition`, { method: "PATCH", body: JSON.stringify({ new_state: newState }) });
export const submitRCA = (id, payload) =>
  apiFetch(`/api/workitems/${id}/rca`, { method: "POST", body: JSON.stringify(payload) });
export const suggestAI_RCA = (id) =>
  apiFetch(`/api/workitems/${id}/suggest-rca`, { method: "POST" });

export const getSignalTimeseries = (minutes = 60) => apiFetch(`/api/analytics/signals/timeseries?minutes=${minutes}`);
export const getIncidentDistribution = () => apiFetch("/api/analytics/incidents/distribution");
export const getMTTRHistory = () => apiFetch("/api/analytics/mttr/history");
