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
  const toggle = document.querySelector("[data-nav-toggle]");
  if (!shell || !toggle) return;
  const closers = document.querySelectorAll("[data-nav-close]");
  const setOpen = (open) => {
    shell.classList.toggle("nav-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    document.body.style.overflow = open ? "hidden" : "";
    if (open) {
      const first = shell.querySelector(".sidebar .nav__link");
      if (first) first.focus({ preventScroll: true });
    } else {
      toggle.focus({ preventScroll: true });
    }
  };
  toggle.addEventListener("click", () => setOpen(!shell.classList.contains("nav-open")));
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
