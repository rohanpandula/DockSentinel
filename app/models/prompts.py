from __future__ import annotations

from enum import StrEnum

from app.extensions import db
from app.time_utils import utcnow_naive


class PromptKey(StrEnum):
    SENTINEL_SYSTEM = "SENTINEL_SYSTEM"
    SENTINEL_ANALYSIS = "SENTINEL_ANALYSIS"
    JSON_OUTPUT_GUARD = "JSON_OUTPUT_GUARD"
    NIGHTLY_SYSTEM = "NIGHTLY_SYSTEM"
    NIGHTLY_REPORT = "NIGHTLY_REPORT"


DEFAULT_PROMPTS: dict[PromptKey, str] = {
    PromptKey.SENTINEL_SYSTEM: (
        "You are an SRE log triage assistant. Prioritize operational risk, use direct evidence "
        "from logs, avoid speculation, and keep recommendations actionable."
    ),
    PromptKey.SENTINEL_ANALYSIS: (
        "You receive Docker container logs. Respond with ONLY one JSON object using keys: "
        "classification, summary, root_cause_hypothesis, fix_suggestion, confidence. "
        "classification must be one of noise, warning, critical. confidence must be between 0.0 and 1.0.\n\n"
        "Classification rubric (pick the lowest level that fits — most log lines are noise):\n"
        "- noise: expected, benign or informational output; debug/startup chatter; a transient error "
        "that the logs show has already recovered (e.g. retry succeeded, reconnect completed); "
        "the word 'error' appearing in normal output such as config echoes or health-check paths.\n"
        "- warning: the service is degraded, retrying, running low on a resource, or showing an "
        "error that will need attention soon but is not yet causing an outage or data loss.\n"
        "- critical: crash or crash loop, data loss or corruption, security incident (auth bypass, "
        "brute force, exposed secrets), service down or unable to serve requests, OOM kill, "
        "disk full, unrecoverable dependency failure.\n\n"
        "Requirements for each field:\n"
        "- summary: one sentence describing what went wrong, mentioning the container name.\n"
        "- root_cause_hypothesis: the single most likely cause based on log evidence. "
        "Be specific (name the subsystem, port, file, config key) rather than generic.\n"
        "- fix_suggestion: a concrete, actionable remediation. Prefer exact shell commands, "
        "docker commands, or configuration changes an operator can run immediately. "
        "If multiple steps are required, number them. Avoid vague advice like "
        "'check the logs' or 'investigate further' — the operator already has the logs. "
        "For noise, a short 'No action needed' is fine.\n"
        "- confidence: your calibrated certainty (0.0-1.0) that the classification AND the "
        "root cause hypothesis are correct. Use values below 0.5 when the logs are ambiguous "
        "or truncated.\n\n"
        "Example (for illustration only — do not copy its content):\n"
        "Container: nginx-proxy\n"
        "<logs>\n"
        "2024-05-01T10:00:01Z [error] 12#12: *3 connect() failed (111: Connection refused) "
        "while connecting to upstream, upstream: http://172.18.0.5:8080/\n"
        "2024-05-01T10:00:02Z [error] 12#12: *4 connect() failed (111: Connection refused) "
        "while connecting to upstream, upstream: http://172.18.0.5:8080/\n"
        "</logs>\n"
        "Response:\n"
        '{"classification": "critical", '
        '"summary": "nginx-proxy cannot reach its upstream at 172.18.0.5:8080 and is returning 502s.", '
        '"root_cause_hypothesis": "The upstream container listening on 172.18.0.5:8080 is down or '
        'not yet started, so every proxied request is refused.", '
        '"fix_suggestion": "1. docker ps -a | grep 172.18.0.5 to find the upstream container. '
        '2. docker logs <upstream> to see why it exited. 3. docker start <upstream> (or fix its '
        'crash) and confirm with curl -I http://172.18.0.5:8080/.", '
        '"confidence": 0.85}'
    ),
    PromptKey.JSON_OUTPUT_GUARD: (
        "Output must be strict JSON only. Do not include markdown, code fences, or extra text. "
        "Do not include keys outside the required schema."
    ),
    PromptKey.NIGHTLY_SYSTEM: (
        "You are generating a concise operator-focused daily health briefing for container operations. "
        "Summarize critical incidents, trends, and practical next actions."
    ),
    PromptKey.NIGHTLY_REPORT: (
        "Generate markdown using sections exactly in this order: Executive Summary, Critical Incidents, "
        "Warnings and Trends, Container Restarts, Recommended Actions (Next 24h)."
    ),
}


class PromptTemplate(db.Model):
    __tablename__ = "prompt_templates"

    key = db.Column(db.String(64), primary_key=True)
    content = db.Column(db.Text, nullable=False)
    default_content = db.Column(db.Text, nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    is_default = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "content": self.content,
            "default_content": self.default_content,
            "version": self.version,
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
