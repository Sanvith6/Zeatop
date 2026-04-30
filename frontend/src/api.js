export async function apiFetch(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
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

export const getWorkItems = () => apiFetch("/api/workitems");
export const getWorkItem = (id) => apiFetch(`/api/workitems/${id}`);
export const transitionWorkItem = (id, newState) =>
  apiFetch(`/api/workitems/${id}/transition`, { method: "PATCH", body: JSON.stringify({ new_state: newState }) });
export const submitRCA = (id, payload) =>
  apiFetch(`/api/workitems/${id}/rca`, { method: "POST", body: JSON.stringify(payload) });
