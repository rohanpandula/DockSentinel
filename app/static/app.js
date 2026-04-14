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
  if (!runBtn || !promptEl) return;

  runBtn.addEventListener("click", async () => {
    const prompt = (promptEl.value || "").trim();
    if (!prompt) {
      setOutputState(statusEl, "error", "Enter a prompt");
      return;
    }
    const payload = { prompt };
    root.querySelectorAll("[data-tryllm-field]").forEach((el) => {
      const v = (el.value || "").trim();
      if (v) payload[el.dataset.tryllmField] = v;
    });

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
        metaEl.textContent = `${data.model || "unknown"} · server ${data.latency_ms || "?"}ms · roundtrip ${roundtrip}ms`;
        resultEl.hidden = false;
        setOutputState(statusEl, "ok", "Done");
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
