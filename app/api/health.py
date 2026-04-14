from __future__ import annotations

from flask import Blueprint

from app.models import SentinelState
from app.schemas.health import HealthResponse
from app.schemas.sentinel import SentinelStateSchema

bp = Blueprint("health_api", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    state = SentinelState.singleton()
    return HealthResponse(runtime=SentinelStateSchema.model_validate(state)).model_dump(), 200
