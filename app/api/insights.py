from flask import Blueprint, current_app
from flask_pydantic import validate

from app.schemas.insights import InsightItem, InsightListResponse, InsightsQuery

bp = Blueprint("insights_api", __name__, url_prefix="/api")


@bp.get("/insights")
@validate(query=InsightsQuery)
def list_insights(query: InsightsQuery):
    services = current_app.extensions["services"]
    events = services.event_repo.get_filtered(
        container=query.container,
        classification=query.classification,
        start=query.start,
        end=query.end,
        limit=query.limit,
        offset=query.offset,
        sort=query.sort,
    )
    return InsightListResponse(
        items=[InsightItem.model_validate(e) for e in events],
        offset=query.offset,
        limit=query.limit,
    )
