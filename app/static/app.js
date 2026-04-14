async function postJSON(url, payload = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return { ok: response.ok, data: await response.json() };
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

  button.addEventListener("click", async () => {
    button.disabled = true;
    setOutputState(output, "pending", labels.pending);
    try {
      const result = await postJSON(endpoint);
      if (result.ok) {
        setOutputState(output, "ok", labels.ok);
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
    });
  }

  runBtn.addEventListener("click", async () => {
    const prompt = (promptEl.value || "").trim();
    if (!prompt) {
      setOutputState(statusEl, "error", "Enter a prompt");
      return;
    }
    const payload = { prompt };
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

    runBtn.disabled = true;
    setOutputState(statusEl, "pending", "Calling LLM…");
    const started = performance.now();
    try {
      const resp = await fetch(`/api/issues/${issueId}/try-llm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await resp.json();
      const roundtrip = Math.round(performance.now() - started);
      if (resp.ok && data.ok) {
        bodyEl.textContent = data.content || "(empty response)";
        if (modelEl) modelEl.textContent = data.model || "unknown";
        metaEl.textContent = `server ${data.latency_ms || "?"}ms · roundtrip ${roundtrip}ms`;
        resultEl.hidden = false;
        setOutputState(statusEl, "ok", "Done");
        loadOllamaModels(root); // refresh loaded-state
      } else {
        setOutputState(statusEl, "error", (data && data.error) || `HTTP ${resp.status}`);
      }
    } catch (err) {
      setOutputState(statusEl, "error", err.message || String(err));
    } finally {
      runBtn.disabled = false;
    }
  });
}

window.addEventListener("DOMContentLoaded", () => {
  wireAnalyzeForm();
  wireTryLLM();
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
