# 🛡️ DockSentinel: AI-Native Observability Agent

DockSentinel is a lightweight, self-hosted AIOps platform designed to cure "log fatigue." It attaches to your local Docker socket, ingests container logs in real-time, and uses Large Language Models (LLMs) to distinguish between routine noise and critical operational failures.

Designed for Home Labs and Self-Hosters who want enterprise-grade observability without the enterprise-grade headache (or cost).

## 🚀 Key Features

### 🧠 1. Universal LLM Connector

Drop-in compatibility with Any OpenAI-compliant API.

- **Local:** Ollama, LM Studio, LocalAI, vLLM (Zero data egress).
- **Cloud:** OpenAI (GPT-4o), Anthropic (via adapters), DeepSeek.

### ⚡ 2. The Sentinel (Real-Time Watchdog)

A background daemon that monitors active log streams. It applies heuristic pre-filtering to detect keywords (Error, Exception, Fatal) and instantly dispatches the log chunk to an LLM for semantic analysis.

- **Outcome:** If the LLM confirms a critical failure, you get a Telegram Alert instantly.

### 🌙 3. The Nightly Briefing

A retrospective scheduled task that aggregates the last 24 hours of logs. It generates a "Daily Gazette" style report summarizing the health, restarts, and anomalies of your entire stack.

### 🎛️ 4. The Control Tower (Web UI)

A reactive, dark-mode dashboard built with Flask and TailwindCSS.

- Visual management of monitoring rules.
- Historical archive of AI insights.
- Prompt Engineering Studio: Edit the AI instructions on the fly to tune fix suggestions.
- Manual "Analyze Now" triggers for specific containers.

## 🏗️ Architecture

DockSentinel utilizes a Host-Agent pattern. It runs as a single container with read-only access to /var/run/docker.sock.

1. **Ingestion:** Reads raw stdout/stderr streams from the Docker Daemon.
2. **Buffering:** Implements sliding window buffering to prevent token overflow.
3. **Inference:** Sends sanitized log chunks to your configured LLM (Local or Cloud).
4. **Persistence:** SQLite database stores settings and analysis history.
5. **Notification:** Telegram Bot API for push alerts.

## 🛠️ Quick Start (Docker Compose)

### Prerequisites

- Docker & Docker Compose installed.
- Optional: A running instance of Ollama or LM Studio for local inference.

### 1. Installation

Clone the repository and navigate to the project folder.
git clone https://github.com/yourusername/docksentinel.git
cd docksentinel
text### 2. Deployment

We use host.docker.internal to allow the container to communicate with LLMs running on your host machine.

Create a docker-compose.yml file (or use the one provided in the repo):
version: '3.8'
services:
docksentinel:
build: .
container_name: docksentinel
ports:

"5000:5000"
volumes:
/var/run/docker.sock:/var/run/docker.sock:ro # Critical: Access to logs
./data:/data                                 # Persistence
environment:
PYTHONUNBUFFERED=1
extra_hosts:
"host.docker.internal:host-gateway" # Required for Linux users to hit localhost
restart: unless-stopped

textStart the stack:
docker-compose up -d --build
text### 3. Access the Dashboard

Navigate to http://localhost:5000.

## ⚙️ Configuration Guide

Configuration is managed entirely via the Web UI (Settings tab).

### Option A: Using LM Studio (Recommended for Beginners)

1. Open LM Studio.
2. Load a model (e.g., Llama 3 or Mistral Instruct).
3. Go to the Local Server tab (<-> icon) and click Start Server.
4. In DockSentinel Settings:
   - **Base URL:** http://host.docker.internal:1234/v1
   - **API Key:** lm-studio (Any string works)
   - **Model:** local-model

### Option B: Using Ollama

1. Ensure Ollama is running: ollama serve.
2. Pull a model: ollama pull llama3.
3. In DockSentinel Settings:
   - **Base URL:** http://host.docker.internal:11434/v1
   - **API Key:** ollama
   - **Model:** llama3 (Must match the pulled model name exactly)

### Option C: Using OpenAI (Cloud)

1. In DockSentinel Settings:
   - **Base URL:** https://api.openai.com/v1
   - **API Key:** sk-proj-.... (Your actual OpenAI Key)
   - **Model:** gpt-4o-mini (Cost-effective and fast)

## 🔔 Setting Up Alerts (Telegram)

1. Open Telegram and search for @BotFather.
2. Send /newbot to create a bot and get your Token.
3. Search for @userinfobot (or similar) to get your personal Chat ID.
4. Enter these credentials in the Settings tab of the dashboard.
5. Toggle Enable Sentinel to start 24/7 monitoring.

## 🧩 Filtering & Optimization

To prevent token waste and alert fatigue, DockSentinel uses a "Smart Exclusion" list. You should exclude noisy containers or the AI agent itself.

**Default Exclusions:**  
docksentinel, ollama, portainer, open-webui

**Heuristics:**  
The Sentinel only triggers an LLM inference call if the log chunk contains high-entropy keywords:  
error, exception, fatal, panic, critical, refused, timeout

## 🛣️ Roadmap

- [ ] Vector Memory: Implement RAG to allow the AI to remember historical errors for specific containers.
- [ ] Multi-Channel Alerts: Support for Discord Webhooks and Slack.
- [ ] Log Export: Export sanitized daily summaries to Markdown/Obsidian vaults.
- [ ] Anomaly Graphs: Visual representation of error rates over time.

## 📄 License

MIT
