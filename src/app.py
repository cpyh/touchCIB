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
from .customer_api import customers_bp
from .dashboard import dashboard_summary
from .dashboard_api import dashboard_bp
from .marketing.generate import (
    StrategyGenerationError,
    generate_customer_strategy,
)
from .marketing.models import (
    DEFAULT_MANAGER_QUOTA,
    DEFAULT_TOP_N,
    DEFAULT_W_CF,
)
from .marketing.roster import query_roster
from .marketing.rules import build_default_engine
from .portfolio import PortfolioInputError, optimize_portfolio
from .scenario import (
    ScenarioInputError,
    ScenarioStoreError,
    create_portfolio_scenario,
    list_portfolio_scenarios,
)


app = Flask(__name__)
app.json.ensure_ascii = False
app.register_blueprint(customers_bp)
app.register_blueprint(dashboard_bp)


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
    except (ValueError, TypeError) as exc:
        return jsonify(error=f"参数不合法：{exc}"), 422
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
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 503


@app.get("/customers/<customer_id>/strategies")
def customer_strategy_list(customer_id: str):
    """Tab3 客户 Top3 策略卡：策略行 + 规则轨迹 + 事件状态。"""
    try:
        return jsonify(customer_strategies(customer_id))
    except CampaignInputError as exc:
        return jsonify(error=str(exc)), 404
    except (ValueError, OSError) as exc:
        app.logger.exception("Customer strategies query failed")
        return jsonify(error=f"customer strategies failed: {exc}"), 503
    except CampaignStoreError:
        app.logger.exception("Customer strategies query failed")
        return jsonify(error="customer strategies are temporarily unavailable"), 503


@app.post("/marketing/strategy/generate")
def marketing_strategy_generate():
    """运营干预：调 w_cf / manager 配额后现场重跑单客户 Top3（不落库）。"""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="request body must be a JSON object"), 400
    try:
        w_cf = float(payload.get("w_cf", DEFAULT_W_CF))
        if not 0.0 <= w_cf <= 1.0:
            raise ValueError("w_cf must be in [0, 1]")
        manager_quota = int(payload.get("manager_quota", DEFAULT_MANAGER_QUOTA))
        if manager_quota < 0:
            raise ValueError("manager_quota must be >= 0")
        top_n = int(payload.get("top_n", DEFAULT_TOP_N))
        if not 1 <= top_n <= 30:
            raise ValueError("top_n must be between 1 and 30")
        customer_id = str(payload.get("customer_id", ""))
        return jsonify(
            generate_customer_strategy(
                customer_id,
                w_cf=w_cf,
                manager_quota=manager_quota,
                top_n=top_n,
            )
        )
    except StrategyGenerationError as exc:
        return jsonify(error=str(exc)), 404
    except (ValueError, TypeError) as exc:
        return jsonify(error=f"参数不合法：{exc}"), 400


@app.get("/marketing/rules")
def marketing_rules():
    """规则引擎元数据（Tab2 轨迹区块的规则清单）。"""
    return jsonify(rules=build_default_engine().metadata())


@app.get("/dashboard/summary")
def dashboard_summary_endpoint():
    """Tab4 看板聚合：模型指标 + 分布 + 漏斗 + KPI + 数据分层行数。"""
    try:
        return jsonify(dashboard_summary())
    except (ValueError, OSError, KeyError):
        app.logger.exception("Dashboard summary failed")
        return jsonify(error="dashboard summary is temporarily unavailable"), 503


def main() -> None:
    app.run(host="0.0.0.0", port=5001)


if __name__ == "__main__":
    main()
