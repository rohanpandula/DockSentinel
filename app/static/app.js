async function postJSON(url, payload = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return { ok: response.ok, data: await response.json() };
}

window.addEventListener("DOMContentLoaded", () => {
  const testLlmButton = document.getElementById("btn-test-llm");
  const testTelegramButton = document.getElementById("btn-test-telegram");
  const output = document.getElementById("settings-test-output");

  if (testLlmButton) {
    testLlmButton.addEventListener("click", async () => {
      output.textContent = "Testing LLM connection...";
      try {
        const result = await postJSON("/api/settings/test-llm");
        output.textContent = result.ok ? "LLM test succeeded." : `LLM test failed: ${result.data.error || "unknown error"}`;
      } catch (error) {
        output.textContent = `LLM test failed: ${error}`;
      }
    });
  }

  if (testTelegramButton) {
    testTelegramButton.addEventListener("click", async () => {
      output.textContent = "Testing Telegram delivery...";
      try {
        const result = await postJSON("/api/telegram/test");
        output.textContent = result.ok
          ? "Telegram test message sent."
          : `Telegram test failed: ${result.data.error || "unknown error"}`;
      } catch (error) {
        output.textContent = `Telegram test failed: ${error}`;
      }
    });
  }
});
