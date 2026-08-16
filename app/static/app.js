async function readJSONBody(response) {
  // Error pages (HTML 500s, proxy errors) aren't JSON: surface the status instead
  // of a SyntaxError.
  const text = await response.text();
  try {
    return text ? JSON.parse(text) : {};
  } catch (_err) {
    return { error: `HTTP ${response.status}` };
  }
}

async function postJSON(url, payload = {}, method = "POST") {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await readJSONBody(response);
  if (!response.ok && !(data && data.error)) data.error = `HTTP ${response.status}`;
  return { ok: response.ok, status: response.status, data };
}

const SECRET_FIELDS = new Set(["llm_api_key", "telegram_token"]);
const INTEGER_FIELDS = new Set([
  "cli_timeout_seconds", "cli_max_retries", "nightly_hour", "nightly_minute",
  "max_input_chars", "max_input_tokens", "reserved_output_tokens",
  "alert_cooldown_minutes", "alert_rate_limit_count", "alert_rate_limit_window_seconds",
  "llm_timeout_seconds", "llm_max_retries", "dedup_window_seconds",
  "container_rate_limit_count", "container_rate_limit_window_seconds",
  "keyword_flush_delay_lines", "chunk_coalesce_window_seconds",
]);

function collectSettingsForm(form) {
  // Only non-empty values; secrets only when the operator actually typed one
  // (blank means "keep the stored secret").
  const payload = {};
  if (!form) return payload;
  for (const el of form.elements) {
    if (!el.name || el.disabled) continue;
    const value = (el.value || "").trim();
    if (value === "") continue;
    if (SECRET_FIELDS.has(el.name) && value === "********") continue;
    if (INTEGER_FIELDS.has(el.name)) {
      const n = Number(value);
      if (!Number.isFinite(n)) continue;
      payload[el.name] = n;
    } else {
      payload[el.name] = value;
    }
  }
  return payload;
}

function setOutputState(el, state, text) {
  if (!el) return;
  el.classList.remove("inline-output--ok", "inline-output--error", "inline-output--pending");
  if (state) el.classList.add(`inline-output--${state}`);
  el.textContent = text || "";
}

function attachTestButton(buttonId, endpoint, labels) {
  const button = document.getElementById(buttonId);
  const output = document.getElementById("settings-test-output");
  if (!button || !output) return;

  const form = button.closest("form");

  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      // Test what's on screen, not what was saved last time: persist the form
      // first, then run the test against the stored settings.
      if (form) {
        setOutputState(output, "pending", "Saving settings…");
        const saved = await postJSON("/api/settings", collectSettingsForm(form), "PUT");
        if (!saved.ok) {
          const reason = (saved.data && saved.data.error) || `HTTP ${saved.status}`;
          setOutputState(output, "error", `Settings not saved — ${typeof reason === "string" ? reason : JSON.stringify(reason)}`);
          return;
        }
        // Secrets were stored; clear the inputs so a re-test doesn't resend them.
        for (const el of form.elements) {
          if (SECRET_FIELDS.has(el.name)) el.value = "";
        }
      }
      setOutputState(output, "pending", `Saved, ${labels.pending.charAt(0).toLowerCase()}${labels.pending.slice(1)}`);
      const result = await postJSON(endpoint);
      if (result.ok) {
        setOutputState(output, "ok", labels.ok);
        toast(labels.ok, "ok");
      } else {
        const reason = (result.data && result.data.error) || "unknown error";
        setOutputState(output, "error", `${labels.fail} — ${reason}`);
      }
    } catch (error) {
      setOutputState(output, "error", `${labels.fail} — ${error.message || error}`);
    } finally {
      button.disabled = false;
    }
  });
}

function wireAnalyzeForm() {
  const form = document.querySelector("[data-analyze-form]");
  if (!form) return;
  const select = form.querySelector("[data-analyze-select]");
  const custom = form.querySelector("[data-analyze-custom]");
  if (!select || !custom) return;

  const reveal = () => {
    const isOther = select.value === "__other__";
    custom.hidden = !isOther;
    if (isOther) custom.focus();
  };

  select.addEventListener("change", reveal);

  form.addEventListener("submit", (event) => {
    if (select.value === "__other__") {
      if (!custom.value.trim()) {
        event.preventDefault();
        custom.focus();
        return;
      }
    } else if (select.value) {
      custom.value = select.value;
    } else {
      event.preventDefault();
      select.focus();
    }
  });

  reveal();
}

function formatBytes(n) {
  if (!n || n < 0) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i += 1; }
  return `${n.toFixed(n >= 100 ? 0 : 1)} ${units[i]}`;
}

async function loadOllamaModels(root) {
  const select = root.querySelector("[data-tryllm-model-select]");
  const hint = root.querySelector("[data-tryllm-model-hint]");
  const baseEl = root.querySelector('[data-tryllm-field="base_url"]');
  if (!select) return;

  const params = new URLSearchParams();
  if (baseEl && baseEl.value.trim()) params.set("base_url", baseEl.value.trim());

  try {
    const resp = await fetch(`/api/ollama/models?${params.toString()}`);
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      if (hint) hint.textContent = `Could not reach Ollama: ${(data && data.error) || resp.status}`;
      return;
    }
    const models = data.models || [];
    const currentValue = select.value;
    [...select.querySelectorAll("option.dyn")].forEach((o) => o.remove());
    const customOpt = select.querySelector('option[value="__custom__"]');
    const beforeCustom = customOpt || null;
    for (const m of models) {
      const opt = document.createElement("option");
      opt.value = m.name;
      opt.textContent = m.loaded
        ? `● ${m.name}${m.size ? " — " + formatBytes(m.size) : ""} (loaded)`
        : `  ${m.name}${m.size ? " — " + formatBytes(m.size) : ""}`;
      opt.className = "dyn";
      select.insertBefore(opt, beforeCustom);
    }
    if (currentValue && [...select.options].some((o) => o.value === currentValue)) {
      select.value = currentValue;
    }
    if (hint) {
      const loaded = data.loaded || [];
      hint.textContent = loaded.length
        ? `${models.length} models · loaded right now: ${loaded.join(", ")}`
        : `${models.length} models · none loaded (first call will load one)`;
    }
  } catch (err) {
    if (hint) hint.textContent = `Could not reach Ollama: ${err.message || err}`;
  }
}

/* ── Journey 6: try another LLM → compare verdicts ───────────────────── */
function runsKey(issueId) { return `ds-runs-${issueId}`; }
function loadRuns(issueId) {
  try { return JSON.parse(localStorage.getItem(runsKey(issueId)) || "[]"); } catch (_e) { return []; }
}
function saveRuns(issueId, runs) {
  try { localStorage.setItem(runsKey(issueId), JSON.stringify(runs.slice(-30))); } catch (_e) { /* quota */ }
}
function fmtWhen(ts) {
  const d = new Date(ts);
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function wireTryLLM() {
  const root = document.querySelector("[data-tryllm]");
  if (!root) return;
  const issueId = root.dataset.issueId;
  const runBtn = root.querySelector("[data-tryllm-run]");
  const promptEl = root.querySelector("[data-tryllm-prompt]");
  const statusEl = root.querySelector("[data-tryllm-status]");
  const resultEl = root.querySelector("[data-tryllm-result]");
  const bodyEl = root.querySelector("[data-tryllm-body]");
  const metaEl = root.querySelector("[data-tryllm-meta]");
  const modelEl = root.querySelector("[data-tryllm-model]");
  const modelSelect = root.querySelector("[data-tryllm-model-select]");
  const modelCustom = root.querySelector("[data-tryllm-model-custom]");
  const baseEl = root.querySelector('[data-tryllm-field="base_url"]');
  const board = root.querySelector("[data-tryllm-board]");
  const boardCount = root.querySelector("[data-tryllm-board-count]");
  const runsBody = root.querySelector("[data-tryllm-runs] tbody");
  const compareEl = root.querySelector("[data-tryllm-compare]");
  const clearBtn = root.querySelector("[data-tryllm-clear]");
  const overrides = root.querySelector("[data-tryllm-overrides]");
  const overrideSummary = root.querySelector("[data-tryllm-override-summary]");
  if (!runBtn || !promptEl) return;

  loadOllamaModels(root);
  if (baseEl) {
    let t;
    baseEl.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(() => loadOllamaModels(root), 400);
    });
  }

  if (modelSelect && modelCustom) {
    modelSelect.addEventListener("change", () => {
      const isCustom = modelSelect.value === "__custom__";
      modelCustom.hidden = !isCustom;
      if (isCustom) modelCustom.focus();
      refreshOverrideSummary();
    });
  }

  function currentOverrides() {
    const payload = {};
    root.querySelectorAll("[data-tryllm-field]").forEach((el) => {
      if (el === modelSelect) return; // handled below
      const v = (el.value || "").trim();
      if (v) payload[el.dataset.tryllmField] = v;
    });
    if (modelSelect) {
      const picked = modelSelect.value;
      if (picked === "__custom__") {
        const custom = (modelCustom && modelCustom.value || "").trim();
        if (custom) payload.model = custom;
      } else if (picked) {
        payload.model = picked;
      }
    }
    return payload;
  }

  function refreshOverrideSummary() {
    if (!overrideSummary) return;
    const o = currentOverrides();
    const parts = [];
    if (o.model) parts.push(o.model);
    if (o.transport) parts.push(o.transport);
    if (o.cli_backend) parts.push(o.cli_backend);
    if (o.base_url) parts.push("custom URL");
    overrideSummary.textContent = parts.length ? `(${parts.join(" · ")})` : "(inheriting Settings)";
  }
  if (overrides) overrides.addEventListener("input", refreshOverrideSummary);
  if (overrides) overrides.addEventListener("change", refreshOverrideSummary);

  let pinned = [];
  function renderBoard() {
    if (!board || !runsBody) return;
    const runs = loadRuns(issueId);
    board.hidden = runs.length === 0;
    if (clearBtn) clearBtn.hidden = runs.length === 0;
    if (boardCount) boardCount.textContent = runs.length ? `(${runs.length})` : "";
    runsBody.innerHTML = "";
    [...runs].reverse().forEach((r) => {
      const tr = document.createElement("tr");
      if (pinned.includes(r.id)) tr.classList.add("is-pinned");
      const ok = r.ok !== false;
      tr.innerHTML = `
        <td><input type="checkbox" aria-label="Pin run for comparison" ${pinned.includes(r.id) ? "checked" : ""}></td>
        <td><span class="text-mono text-sm break">${escapeHtml(r.model || "?")}</span>${r.transport ? `<span class="text-tertiary text-xs"> · ${escapeHtml(r.transport)}</span>` : ""}${ok ? "" : ' <span class="badge badge--critical badge--no-dot">error</span>'}</td>
        <td><span class="runs__prompt" title="${escapeHtml(r.prompt)}">${escapeHtml(r.prompt)}</span></td>
        <td class="is-num text-mono text-sm">${r.latency_ms ? r.latency_ms + " ms" : "—"}</td>
        <td class="text-tertiary text-xs text-mono">${fmtWhen(r.ts)}</td>
        <td class="is-num"><span class="btn-row" style="justify-content:flex-end"><button type="button" class="btn btn--sm btn--ghost" data-run-show>show</button><button type="button" class="btn btn--sm btn--ghost" data-run-again title="Run the same prompt on the same model again">again</button></span></td>`;
      tr.querySelector("input").addEventListener("change", (ev) => {
        if (ev.target.checked) { pinned.push(r.id); if (pinned.length > 2) pinned = pinned.slice(-2); }
        else pinned = pinned.filter((id) => id !== r.id);
        syncPins(); // in place: re-rendering the table here would drop the row the user just clicked
      });
      tr.querySelector("[data-run-show]").addEventListener("click", () => showResult(r));
      tr.querySelector("[data-run-again]").addEventListener("click", () => run(r.prompt, r.overrides || {}));
      runsBody.appendChild(tr);
    });
    syncPins();
  }

  // Pin state only: rows keep their DOM nodes so a click never lands on a stale row.
  function syncPins() {
    const runs = loadRuns(issueId);
    if (runsBody) {
      [...runsBody.rows].forEach((tr, i) => {
        const r = [...runs].reverse()[i];
        if (!r) return;
        const on = pinned.includes(r.id);
        tr.classList.toggle("is-pinned", on);
        const box = tr.querySelector("input");
        if (box && box.checked !== on) box.checked = on;
      });
    }
    if (!compareEl) return;
    const cols = runs.filter((r) => pinned.includes(r.id));
    compareEl.hidden = cols.length < 2;
    compareEl.innerHTML = "";
    cols.forEach((r) => {
      const col = document.createElement("div");
      col.className = "compare__col";
      col.innerHTML = `<div class="compare__head"><span class="compare__model">${escapeHtml(r.model || "?")}</span><span class="text-tertiary text-xs text-mono">${r.latency_ms || "?"} ms · ${fmtWhen(r.ts)}</span></div><div class="compare__body"></div>`;
      col.querySelector(".compare__body").textContent = r.content || r.error || "";
      compareEl.appendChild(col);
    });
  }

  function showResult(r) {
    bodyEl.textContent = r.content || r.error || "(empty response)";
    if (modelEl) modelEl.textContent = r.model || "unknown";
    metaEl.textContent = `server ${r.latency_ms || "?"}ms${r.roundtrip ? ` · roundtrip ${r.roundtrip}ms` : ""} · ${fmtWhen(r.ts)}`;
    resultEl.hidden = false;
    resultEl.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  async function run(prompt, ov) {
    const payload = { prompt, ...ov };
    runBtn.disabled = true;
    setOutputState(statusEl, "pending", `Calling ${ov.model || "default model"}…`);
    const started = performance.now();
    const rec = { id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, ts: Date.now(), prompt, overrides: ov, transport: ov.transport || "" };
    try {
      const resp = await fetch(`/api/issues/${issueId}/try-llm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      rec.roundtrip = Math.round(performance.now() - started);
      if (resp.ok && data.ok) {
        rec.ok = true; rec.content = data.content || ""; rec.model = data.model || ov.model || "unknown"; rec.latency_ms = data.latency_ms;
        setOutputState(statusEl, "ok", "Done — added to runs below");
        loadOllamaModels(root); // refresh loaded-state
      } else {
        rec.ok = false; rec.error = (data && data.error) || `HTTP ${resp.status}`; rec.model = ov.model || "(default)";
        setOutputState(statusEl, "error", rec.error);
      }
    } catch (err) {
      rec.ok = false; rec.error = err.message || String(err); rec.model = ov.model || "(default)";
      setOutputState(statusEl, "error", rec.error);
    } finally {
      runBtn.disabled = false;
    }
    const runs = loadRuns(issueId);
    runs.push(rec);
    saveRuns(issueId, runs);
    showResult(rec);
    renderBoard();
  }

  runBtn.addEventListener("click", () => {
    const prompt = (promptEl.value || "").trim();
    if (!prompt) {
      setOutputState(statusEl, "error", "Enter a prompt");
      return;
    }
    run(prompt, currentOverrides());
  });
  if (clearBtn) clearBtn.addEventListener("click", () => { saveRuns(issueId, []); pinned = []; renderBoard(); resultEl.hidden = true; });

  refreshOverrideSummary();
  renderBoard();
}

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ── Journey 1: "since I last looked" ────────────────────────────────── */
const SEEN_KEY = "ds-last-seen";
function wireSinceLastSeen() {
  let last = 0;
  try { last = Number(localStorage.getItem(SEEN_KEY) || 0); } catch (_e) { /* ignore */ }
  const rows = [...document.querySelectorAll("[data-ts]")];
  let fresh = 0;
  if (last) {
    rows.forEach((row) => {
      const ts = Date.parse(row.dataset.ts + (row.dataset.ts.endsWith("Z") ? "" : "Z"));
      if (ts && ts > last) {
        fresh += 1;
        row.classList.add("is-new");
        const marker = row.querySelector("[data-new-marker]");
        if (marker) marker.hidden = false;
      }
    });
  }
  const pill = document.querySelector("[data-since-pill]");
  if (pill && last) {
    const d = new Date(last);
    pill.querySelector("[data-since-count]").textContent = String(fresh);
    pill.querySelector("[data-since-label]").textContent = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    pill.hidden = false;
  }
  // Only the Now page advances the marker (glance path), after the operator has had a look.
  if (document.querySelector("[data-recent-events]")) {
    const stamp = () => { try { localStorage.setItem(SEEN_KEY, String(Date.now())); } catch (_e) { /* ignore */ } };
    window.addEventListener("pagehide", stamp);
    setTimeout(stamp, 8000);
  }
}

/* ── Journey 4: guided setup ─────────────────────────────────────────── */
function wireSetup() {
  const root = document.querySelector("[data-setup]");
  if (!root) return;
  const panels = [...root.querySelectorAll("[data-setup-panel]")];
  const tabs = [...root.querySelectorAll("[data-setup-tab]")];
  const show = (n) => {
    panels.forEach((p) => { p.hidden = p.dataset.setupPanel !== String(n); });
    tabs.forEach((t) => {
      const on = t.dataset.setupTab === String(n);
      t.setAttribute("aria-selected", String(on));
      t.closest(".stepper__step").classList.toggle("is-current", on);
    });
    root.dataset.step = String(n);
  };
  tabs.forEach((t) => t.addEventListener("click", () => show(t.dataset.setupTab)));
  root.querySelectorAll("[data-setup-next]").forEach((b) => b.addEventListener("click", () => show(b.dataset.setupNext)));

  // transport toggle
  const llmForm = root.querySelector('[data-setup-form="llm"]');
  if (llmForm) {
    const transport = llmForm.querySelector('[name="llm_transport"]');
    const sync = () => {
      const cli = transport.value === "cli";
      llmForm.querySelectorAll("[data-setup-api-only]").forEach((el) => { el.hidden = cli; });
      llmForm.querySelectorAll("[data-setup-cli-only]").forEach((el) => { el.hidden = !cli; });
    };
    transport.addEventListener("change", sync);
    sync();
    // model suggestions from Ollama
    const base = llmForm.querySelector('[name="llm_base_url"]');
    const list = llmForm.querySelector("#setup-models");
    const hint = llmForm.querySelector("[data-setup-models-hint]");
    const loadModels = async () => {
      if (!list) return;
      const params = new URLSearchParams();
      if (base && base.value.trim()) params.set("base_url", base.value.trim());
      try {
        const resp = await fetch(`/api/ollama/models?${params}`);
        const data = await resp.json();
        if (!resp.ok || !data.ok) { if (hint) hint.textContent = "Not an Ollama server (or unreachable) — type the model name."; return; }
        list.innerHTML = "";
        (data.models || []).forEach((m) => { const o = document.createElement("option"); o.value = m.name; list.appendChild(o); });
        if (hint) hint.textContent = `${(data.models || []).length} Ollama models found — pick one from the list.`;
      } catch (_e) { if (hint) hint.textContent = "Could not reach the model server yet."; }
    };
    loadModels();
    if (base) { let t; base.addEventListener("input", () => { clearTimeout(t); t = setTimeout(loadModels, 500); }); }
  }

  const saveForm = async (form, statusEl) => {
    setOutputState(statusEl, "pending", "Saving…");
    const saved = await postJSON("/api/settings", collectSettingsForm(form), "PUT");
    if (!saved.ok) {
      const reason = (saved.data && saved.data.error) || `HTTP ${saved.status}`;
      setOutputState(statusEl, "error", `Not saved — ${typeof reason === "string" ? reason : JSON.stringify(reason)}`);
      return false;
    }
    for (const el of form.elements) if (SECRET_FIELDS.has(el.name)) el.value = "";
    return true;
  };

  root.querySelectorAll("[data-setup-test]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const kind = btn.dataset.setupTest;
      const form = root.querySelector(`[data-setup-form="${kind}"]`);
      const statusEl = root.querySelector(`[data-setup-status="${kind}"]`);
      btn.disabled = true;
      try {
        if (!(await saveForm(form, statusEl))) return;
        setOutputState(statusEl, "pending", kind === "llm" ? "Saved. Asking the model for a pong…" : "Saved. Sending a Telegram message…");
        const result = await postJSON(kind === "llm" ? "/api/settings/test-llm" : "/api/telegram/test");
        if (result.ok) {
          setOutputState(statusEl, "ok", kind === "llm" ? "LLM reachable — step done. Reloading…" : "Message delivered — check your phone. Reloading…");
          toast(kind === "llm" ? "LLM reachable" : "Telegram message delivered", "ok");
          setTimeout(() => { window.location.href = "/dashboard?setup=1"; }, 900);
        } else {
          const reason = (result.data && result.data.error) || "unknown error";
          setOutputState(statusEl, "error", `${kind === "llm" ? "LLM test failed" : "Telegram test failed"} — ${reason}`);
        }
      } catch (err) {
        setOutputState(statusEl, "error", err.message || String(err));
      } finally {
        btn.disabled = false;
      }
    });
  });

  root.querySelectorAll("[data-setup-save]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const kind = btn.dataset.setupSave;
      const form = root.querySelector(`[data-setup-form="${kind}"]`);
      const statusEl = root.querySelector(`[data-setup-status="${kind}"]`);
      btn.disabled = true;
      try {
        if (await saveForm(form, statusEl)) setOutputState(statusEl, "ok", "Saved. Now send /start to the bot and press Detect.");
      } finally { btn.disabled = false; }
    });
  });

  const detect = root.querySelector("[data-setup-detect]");
  if (detect) {
    detect.addEventListener("click", async () => {
      const hint = root.querySelector("[data-setup-detect-hint]");
      const input = root.querySelector('[name="telegram_chat_id"]');
      detect.disabled = true;
      try {
        const resp = await fetch("/api/telegram/detect-chat");
        const data = await readJSONBody(resp);
        if (resp.ok && data.ok) {
          input.value = data.chat_id;
          if (hint) hint.textContent = `Detected ${data.title || data.type || "chat"} · ${data.chat_id}. Press “Save & send test message”.`;
          input.focus();
        } else if (hint) {
          hint.textContent = (data && data.error) || `HTTP ${resp.status}`;
        }
      } catch (err) { if (hint) hint.textContent = err.message || String(err); }
      finally { detect.disabled = false; }
    });
  }
}

/* ── Prompt studio: tabs, dirty flag, stats ──────────────────────────── */
function wirePromptStudio() {
  const form = document.querySelector("[data-prompt-editor]");
  if (!form) return;
  const text = form.querySelector("[data-prompt-text]");
  const def = form.querySelector("[data-prompt-default]");
  const panes = form.querySelector("[data-prompt-panes]");
  const dirty = form.querySelector("[data-prompt-dirty]");
  const stats = form.querySelector("[data-prompt-stats]");
  const original = text.value;
  const defaultText = def ? def.textContent : "";
  const update = () => {
    const v = text.value;
    if (dirty) dirty.hidden = v === original;
    if (stats) stats.textContent = `${v.length} chars · ${v.split("\n").length} lines${v.trim() === defaultText.trim() ? " · matches default" : ""}`;
  };
  text.addEventListener("input", update);
  update();
  form.querySelectorAll("[data-prompt-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const mode = btn.dataset.promptTab;
      form.querySelectorAll("[data-prompt-tab]").forEach((b) => { const on = b === btn; b.classList.toggle("chip--active", on); b.setAttribute("aria-selected", String(on)); });
      panes.classList.toggle("prompt-panes--side", mode === "side");
      form.querySelectorAll("[data-prompt-pane]").forEach((p) => { p.hidden = mode !== "side" && p.dataset.promptPane !== mode; });
    });
  });
  const copy = form.querySelector("[data-prompt-copy-default]");
  if (copy) copy.addEventListener("click", () => { text.value = defaultText; update(); text.focus(); });
  window.addEventListener("beforeunload", (e) => { if (dirty && !dirty.hidden && !form.dataset.submitting) { e.preventDefault(); e.returnValue = ""; } });
  form.addEventListener("submit", () => { form.dataset.submitting = "1"; });
}


/* ── Shell: theme, drawer, toasts, section nav ───────────────────────── */
const THEME_KEY = "ds-theme";

function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "light" || theme === "dark") root.setAttribute("data-theme", theme);
  else root.removeAttribute("data-theme");
}

function wireThemeToggle() {
  const btn = document.querySelector("[data-theme-toggle]");
  if (!btn) return;
  btn.addEventListener("click", () => {
    let current = null;
    try { current = localStorage.getItem(THEME_KEY); } catch (_e) { /* private mode */ }
    // auto → light → dark → auto
    const next = current === "light" ? "dark" : current === "dark" ? null : "light";
    try {
      if (next) localStorage.setItem(THEME_KEY, next);
      else localStorage.removeItem(THEME_KEY);
    } catch (_e) { /* ignore */ }
    applyTheme(next);
  });
}

function wireNavDrawer() {
  const shell = document.getElementById("shell");
  const toggles = [...document.querySelectorAll("[data-nav-toggle]")];
  const toggle = toggles[0];
  if (!shell || !toggle) return;
  const closers = document.querySelectorAll("[data-nav-close]");
  const setOpen = (open) => {
    shell.classList.toggle("nav-open", open);
    toggles.forEach((t) => t.setAttribute("aria-expanded", String(open)));
    document.body.style.overflow = open ? "hidden" : "";
    if (open) {
      const first = shell.querySelector(".sidebar .nav__link");
      if (first) first.focus({ preventScroll: true });
    } else {
      toggle.focus({ preventScroll: true });
    }
  };
  toggles.forEach((t) => t.addEventListener("click", () => setOpen(!shell.classList.contains("nav-open"))));
  closers.forEach((el) => {
    el.hidden = false;
    el.addEventListener("click", () => setOpen(false));
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && shell.classList.contains("nav-open")) setOpen(false);
  });
  const mq = window.matchMedia("(min-width: 901px)");
  mq.addEventListener("change", () => { if (mq.matches) setOpen(false); });
}

function toast(message, kind = "info", ttl = 4000) {
  const region = document.querySelector("[data-toasts]");
  if (!region) return;
  const el = document.createElement("div");
  el.className = `toast toast--${kind}`;
  el.setAttribute("role", "status");
  el.textContent = message;
  region.appendChild(el);
  setTimeout(() => el.remove(), ttl);
}
window.dsToast = toast;

function wireSectionNav() {
  const nav = document.querySelector("[data-section-nav]");
  if (!nav || !("IntersectionObserver" in window)) return;
  const links = [...nav.querySelectorAll('a[href^="#"]')];
  const sections = links
    .map((a) => document.getElementById(a.getAttribute("href").slice(1)))
    .filter(Boolean);
  if (!sections.length) return;
  const setActive = (id) => links.forEach((a) => a.classList.toggle("is-active", a.getAttribute("href") === `#${id}`));
  const io = new IntersectionObserver((entries) => {
    const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
    if (visible.length) setActive(visible[0].target.id);
  }, { rootMargin: "-10% 0px -70% 0px", threshold: 0 });
  sections.forEach((s) => io.observe(s));
  setActive(sections[0].id);
  // Deep links from the Overview checklist (#llm, #alerts) should highlight too.
  if (location.hash) {
    const target = document.getElementById(location.hash.slice(1));
    if (target) setActive(target.id);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  wireThemeToggle();
  wireNavDrawer();
  wireSectionNav();
  wireAnalyzeForm();
  wireTryLLM();
  wireSinceLastSeen();
  wireSetup();
  wirePromptStudio();
  attachTestButton("btn-test-llm", "/api/settings/test-llm", {
    pending: "Testing LLM connection…",
    ok: "LLM reachable",
    fail: "LLM test failed",
  });
  attachTestButton("btn-test-telegram", "/api/telegram/test", {
    pending: "Sending Telegram test message…",
    ok: "Telegram message delivered",
    fail: "Telegram test failed",
  });
});
