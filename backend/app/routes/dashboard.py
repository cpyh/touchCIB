from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..errors import ValidationError
from ..services.dashboard_service import (
    get_dashboard_overview,
    get_dashboard_portfolio,
)


dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/api/v1/dashboard")


def success(data, status: int = 200):
    return jsonify({"code": 0, "message": "success", "data": data}), status


def _optional_scenario_id() -> str | None:
    value = request.args.get("scenario_id")
    if value is None:
        return None
    value = value.strip()
    if not value or len(value) > 64:
        raise ValidationError("invalid scenario_id")
    return value


@dashboard_bp.get("/overview")
def dashboard_overview():
    return success(get_dashboard_overview(scenario_id=_optional_scenario_id()))


@dashboard_bp.get("/portfolio")
def dashboard_portfolio():
    scenario_id = _optional_scenario_id()
    if scenario_id is None:
        raise ValidationError("scenario_id is required")
    return success(get_dashboard_portfolio(scenario_id))
