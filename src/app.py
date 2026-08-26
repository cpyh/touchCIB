from flask import Flask, jsonify, request

from .campaign import (
    CampaignInputError,
    CampaignStoreError,
    create_responded_event,
    create_sent_event,
    customer_strategies,
    list_campaign_events,
)
from .customer import CustomerProfileError, get_customer_profile
from .dashboard import dashboard_summary
from .marketing.roster import query_roster
from .portfolio import PortfolioInputError, optimize_portfolio
from .scenario import (
    ScenarioInputError,
    ScenarioStoreError,
    create_portfolio_scenario,
    list_portfolio_scenarios,
)


app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    """允许前端开发服务器（vinext :3000）跨域调用 API。"""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


@app.route("/<path:path>", methods=["OPTIONS"])
def preflight(path: str):
    return jsonify(status="ok")


@app.get("/health")
def health_check():
    """Report whether the HTTP service is available."""
    return jsonify(status="ok")


@app.get("/customers/<customer_id>/profile")
def customer_profile(customer_id: str):
    try:
        profile = get_customer_profile(customer_id)
    except CustomerProfileError:
        app.logger.exception("Customer profile query failed")
        return jsonify(error="customer profile is temporarily unavailable"), 503

    if profile is None:
        return jsonify(error="customer not found"), 404
    return jsonify(profile)


@app.post("/portfolio/optimize")
def portfolio_optimize():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="request body must be a JSON object"), 400

    try:
        return jsonify(optimize_portfolio(payload))
    except PortfolioInputError as exc:
        return jsonify(error=str(exc)), 400
    except (RuntimeError, ValueError) as exc:
        return jsonify(error=f"portfolio optimization failed: {exc}"), 422


@app.get("/portfolio/scenarios")
def portfolio_scenarios():
    try:
        return jsonify(scenarios=list_portfolio_scenarios())
    except ScenarioStoreError:
        app.logger.exception("Portfolio scenario query failed")
        return jsonify(error="portfolio scenarios are temporarily unavailable"), 503


@app.post("/portfolio/scenarios")
def save_portfolio_scenario():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="request body must be a JSON object"), 400

    try:
        return jsonify(create_portfolio_scenario(payload)), 201
    except ScenarioInputError as exc:
        return jsonify(error=str(exc)), 400
    except ScenarioStoreError:
        app.logger.exception("Portfolio scenario save failed")
        return jsonify(error="portfolio scenario could not be saved"), 503


def _campaign_event_payload() -> dict:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise CampaignInputError("request body must be a JSON object")
    return payload


def _parse_datetime(value, field: str):
    from datetime import datetime

    if value is None:
        return None
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise CampaignInputError(
                f"{field} must be an ISO datetime, got {value!r}"
            ) from exc
    raise CampaignInputError(f"{field} must be an ISO datetime string")


def _parse_date(value, field: str):
    from datetime import date

    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CampaignInputError(
                f"{field} must be an ISO date (YYYY-MM-DD), got {value!r}"
            ) from exc
    raise CampaignInputError(f"{field} is required (YYYY-MM-DD)")


@app.post("/campaign/events")
def campaign_events_create():
    """埋点入口：event_type=sent 标记已触达；responded 过归因校验后落库。"""
    try:
        payload = _campaign_event_payload()
    except CampaignInputError as exc:
        return jsonify(error=str(exc)), 400

    event_type = payload.get("event_type")
    try:
        if event_type == "sent":
            event = create_sent_event(
                strategy_id=str(payload.get("strategy_id", "")),
                occurred_at=_parse_datetime(payload.get("occurred_at"), "occurred_at"),
            )
        elif event_type == "responded":
            amount = payload.get("amount")
            if amount is not None and (
                isinstance(amount, bool) or not isinstance(amount, (int, float))
            ):
                raise CampaignInputError("amount must be a number")
            event = create_responded_event(
                customer_id=str(payload.get("customer_id", "")),
                product_id=str(payload.get("product_id", "")),
                buy_date=_parse_date(payload.get("buy_date"), "buy_date"),
                amount=float(amount) if amount is not None else None,
                occurred_at=_parse_datetime(payload.get("occurred_at"), "occurred_at"),
                window_days=int(payload.get("window_days", 30)),
            )
        else:
            return jsonify(error="event_type must be 'sent' or 'responded'"), 400
    except CampaignInputError as exc:
        return jsonify(error=str(exc)), 422
    except CampaignStoreError:
        app.logger.exception("Campaign event write failed")
        return jsonify(error="campaign event could not be recorded"), 503
    return jsonify(event), 201


@app.get("/campaign/events")
def campaign_events_list():
    """事件查询：?customer_id= 或 ?strategy_id= 过滤。"""
    try:
        events = list_campaign_events(
            customer_id=request.args.get("customer_id"),
            strategy_id=request.args.get("strategy_id"),
        )
    except CampaignInputError as exc:
        return jsonify(error=str(exc)), 400
    except CampaignStoreError:
        app.logger.exception("Campaign event query failed")
        return jsonify(error="campaign events are temporarily unavailable"), 503
    return jsonify(events=events)


@app.get("/marketing/roster")
def marketing_roster():
    """Tab3 A1 响应名单（默认概率降序，分页 + 渠道/最低概率筛选）。"""
    try:
        return jsonify(
            query_roster(
                page=int(request.args.get("page", 1)),
                size=int(request.args.get("size", 50)),
                channel=request.args.get("channel"),
                min_prob=(
                    float(request.args["min_prob"])
                    if request.args.get("min_prob") is not None
                    else None
                ),
                sort=request.args.get("sort", "prob_desc"),
            )
        )
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400


@app.get("/customers/<customer_id>/strategies")
def customer_strategy_list(customer_id: str):
    """Tab3 客户 Top3 策略卡：策略行 + 规则轨迹 + 事件状态。"""
    try:
        return jsonify(customer_strategies(customer_id))
    except CampaignInputError as exc:
        return jsonify(error=str(exc)), 404
    except CampaignStoreError:
        app.logger.exception("Customer strategies query failed")
        return jsonify(error="customer strategies are temporarily unavailable"), 503


@app.get("/dashboard/summary")
def dashboard_summary_endpoint():
    """Tab4 看板聚合：模型指标 + 分布 + 漏斗 + KPI + 数据分层行数。"""
    try:
        return jsonify(dashboard_summary())
    except (ValueError, OSError):
        app.logger.exception("Dashboard summary failed")
        return jsonify(error="dashboard summary is temporarily unavailable"), 503


def main() -> None:
    app.run(host="0.0.0.0", port=5001)


if __name__ == "__main__":
    main()
