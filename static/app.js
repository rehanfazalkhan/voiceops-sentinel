const state = { calls: [], selected: null };
const byId = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json", ...options.headers }, ...options });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || "Request failed");
  return response.json();
}

function render() {
  const calls = byId("call-list");
  const selected = state.selected;
  const active = state.calls.filter((call) => call.status === "active").length;
  const approvals = state.calls.filter((call) => call.status === "requires_approval").length;
  byId("active-count").textContent = active;
  byId("approval-count").textContent = approvals;
  calls.innerHTML = state.calls.length ? state.calls.map((call) => `<button class="call-card ${selected?.id === call.id ? "selected" : ""}" data-id="${escapeHtml(call.id)}"><b>${escapeHtml(call.caller_reference)}</b><small>${escapeHtml(call.channel.toUpperCase())} · ${escapeHtml(new Date(call.updated_at).toLocaleTimeString())}</small><span class="badge">${escapeHtml(call.status.replaceAll("_", " "))}</span></button>`).join("") : '<p class="empty">No active conversations.</p>';
  document.querySelectorAll(".call-card").forEach((node) => node.onclick = () => { state.selected = state.calls.find((call) => call.id === node.dataset.id); render(); });
  const conversation = byId("conversation");
  const assessment = byId("assessment");
  const approvalButton = byId("approve");
  if (!selected) { conversation.innerHTML = '<div class="empty-state"><strong>Governed voice response</strong><p>Select a call to inspect the redacted transcript, specialist trace, and approval status.</p></div>'; assessment.innerHTML = '<p class="empty">No recommendation selected.</p>'; byId("case-title").textContent = "Select a conversation"; approvalButton.disabled = true; return; }
  byId("case-title").textContent = selected.caller_reference;
  const pill = byId("status-pill"); pill.textContent = selected.status.replaceAll("_", " "); pill.className = `status ${selected.status}`;
  conversation.innerHTML = selected.transcript.map((turn) => `<article class="turn ${turn.speaker === "agent" ? "agent" : "caller"}"><span class="who">${escapeHtml(turn.speaker)}${turn.redacted ? " · sensitive content redacted" : ""}</span>${escapeHtml(turn.text)}</article>`).join("") || '<p class="empty">No transcript turns yet.</p>';
  const result = selected.latest_assessment;
  assessment.innerHTML = result ? `<span class="risk ${escapeHtml(result.risk)}">${escapeHtml(result.risk)} risk</span><h3>Intent</h3><p>${escapeHtml(result.intent.replaceAll("_", " "))}</p><h3>Recommended action</h3><p>${escapeHtml(result.recommended_action)}</p><h3>Supervisor summary</h3><p>${escapeHtml(result.supervisor_summary)}</p><h3>Approved sources</h3><ul class="citations">${result.citations.map((source) => `<li>${escapeHtml(source.title)} (${escapeHtml(source.source_id)})</li>`).join("")}</ul>` : '<p class="empty">Awaiting first assessment.</p>';
  approvalButton.disabled = selected.status !== "requires_approval";
}

async function refresh() { state.calls = await api("/api/calls"); if (state.selected) state.selected = state.calls.find((call) => call.id === state.selected.id) || null; render(); }
byId("refresh").onclick = refresh;
byId("utterance-form").onsubmit = async (event) => { event.preventDefault(); if (!state.selected) return; const input = byId("utterance"); if (!input.value.trim()) return; await api(`/api/calls/${state.selected.id}/utterances`, { method: "POST", body: JSON.stringify({ text: input.value, source: "operator" }) }); input.value = ""; await refresh(); };
byId("approve").onclick = async () => { if (!state.selected) return; await api(`/api/calls/${state.selected.id}/approve`, { method: "POST", headers: { "X-VoiceOps-Development-Role": "voiceops_supervisor" } }); await refresh(); };
api("/readyz").then((result) => { byId("readiness").textContent = result.status === "ready" ? `Runtime ready · ${result.environment}` : "Production configuration incomplete"; }).catch(() => { byId("readiness").textContent = "Runtime unavailable"; });
refresh();
