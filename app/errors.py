from __future__ import annotations

from flask import Flask, jsonify
from flask_pydantic.exceptions import ValidationError


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ValidationError)
    def _handle_validation(err: ValidationError):
        # Remap Flask-Pydantic's {"validation_error": ...} to the codebase's
        # {"error": ...} envelope (Pattern S-4). Surface the first error message
        # but do NOT echo user-supplied values — `err` stringification is
        # schema-derived and safe; raw payload fields are omitted.
        parts: list[str] = []
        for attr in ("body_params", "form_params", "query_params", "path_params"):
            raw = getattr(err, attr, None) or []
            for item in raw:
                msg = item.get("msg") if isinstance(item, dict) else None
                if msg:
                    parts.append(str(msg))
        message = parts[0] if parts else "validation error"
        return jsonify({"error": message}), 400
