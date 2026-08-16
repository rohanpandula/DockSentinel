from datetime import timedelta

from flask import Blueprint, current_app, jsonify
from flask_pydantic import validate

from app.extensions import db
from app.schemas.mutes import ContainerMuteSchema, MuteListResponse, PutMuteBody
from app.time_utils import utcnow_naive

bp = Blueprint("mutes_api", __name__, url_prefix="/api")


@bp.get("/mutes")
def list_mutes():
    services = current_app.extensions["services"]
    mutes = services.mute_repo.list_active(utcnow_naive())
    return MuteListResponse(items=[ContainerMuteSchema.model_validate(m) for m in mutes]).model_dump(), 200


@bp.put("/mutes/<path:container_name>")
@validate(body=PutMuteBody)
def put_mute(container_name: str, body: PutMuteBody):
    services = current_app.extensions["services"]
    name = container_name.strip()
    if not name:
        return jsonify({"error": "container_name required"}), 400
    until = utcnow_naive() + timedelta(hours=body.hours) if body.hours is not None else None
    mute = services.mute_repo.upsert(name, until, body.reason)
    db.session.commit()
    return ContainerMuteSchema.model_validate(mute).model_dump(), 200


@bp.delete("/mutes/<path:container_name>")
def delete_mute(container_name: str):
    services = current_app.extensions["services"]
    if not services.mute_repo.delete(container_name.strip()):
        return jsonify({"error": "mute not found"}), 404
    db.session.commit()
    return jsonify({"deleted": True}), 200
