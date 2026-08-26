from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..services.ai_summary_service import generate_ai_summary
from ..services.customer_service import create_customer, list_customers
from ..services.profile_service import get_customer_profile


customers_bp = Blueprint("customers", __name__, url_prefix="/api/v1/customers")


def success(data, status: int = 200):
    return jsonify({"code": 0, "message": "success", "data": data}), status


@customers_bp.get("")
def customers_list():
    data = list_customers(
        page=request.args.get("page", default=1, type=int),
        page_size=request.args.get("page_size", default=20, type=int),
        keyword=request.args.get("keyword"),
        risk_appetite=request.args.get("risk_appetite"),
        vip_level=request.args.get("vip_level"),
        city=request.args.get("city"),
    )
    return success(data)


@customers_bp.post("")
def customer_create():
    return success(create_customer(request.get_json(silent=True)), 201)


@customers_bp.get("/<customer_id>/profile")
def customer_profile(customer_id: str):
    return success(get_customer_profile(customer_id))


@customers_bp.post("/<customer_id>/ai-summary")
def customer_ai_summary(customer_id: str):
    return success(generate_ai_summary(customer_id))
