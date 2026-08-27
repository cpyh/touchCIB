from flask import Flask, Response, jsonify, request, stream_with_context

from .business_date import DEFAULT_BUSINESS_DATE, parse_business_date
from .campaign import (
    CampaignInputError,
    CampaignStoreError,
    create_responded_event,
    create_sent_event,
    customer_strategies,
    list_campaign_events,
    simulate_holding_purchase,
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
    DEFAULT_MANAGER_DAILY_CAPACITY,
    DEFAULT_MANAGER_POOL_SIZE,
    DEFAULT_TOP_N,
)
from .marketing.roster import query_roster
from .marketing.rules import build_default_engine
from .marketing.tasks import MarketingTaskStoreError, query_marketing_tasks
from .partA1serving.feature_service import FeatureAssemblyError
from .partA1serving.runtime import get_mysql_predictor
from .portfolio import (
    PortfolioInputError,
    ScenarioInputError,
    ScenarioStoreError,
    create_portfolio_scenario,
    generate_ai_analysis,
    list_portfolio_scenarios,
    optimize_portfolio,
    stream_ai_analysis,
    stream_chat,
)
from .warehouse_jobs import (
    PipelineBusyError,
    latest_pipeline_run,
    pipeline_definition,
    start_pipeline_run,
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
        business_date = parse_business_date(request.args.get("business_date"))
        profile = get_customer_profile(customer_id, business_date)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
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
        include_business = payload.get("include_business", True)
        if not isinstance(include_business, bool):
            raise PortfolioInputError("include_business must be a boolean")
        return jsonify(
            optimize_portfolio(payload, include_business=include_business)
        )
    except PortfolioInputError as exc:
        return jsonify(error=str(exc)), 400
    except (RuntimeError, ValueError) as exc:
        return jsonify(error=f"portfolio optimization failed: {exc}"), 422


@app.post("/portfolio/ai-analysis")
def portfolio_ai_analysis():
    """组合方案 AI 解读：前端传方案上下文，后端调 DeepSeek 返回一段文本。"""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="request body must be a JSON object"), 400
    try:
        return jsonify(text=generate_ai_analysis(payload))
    except (RuntimeError, ValueError) as exc:
        return jsonify(error=f"portfolio AI analysis failed: {exc}"), 503


@app.post("/portfolio/ai-analysis/stream")
def portfolio_ai_analysis_stream():
    """组合方案 AI 解读（SSE 流式输出）。"""
    import json as _json

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="request body must be a JSON object"), 400

    def generate():
        try:
            for delta in stream_ai_analysis(payload):
                yield f"data: {_json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
        except (RuntimeError, ValueError) as exc:
            yield f"data: {_json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/portfolio/chat/stream")
def portfolio_chat_stream():
    """投顾 AI 助手多轮对话（SSE 流式）。"""
    import json as _json

    payload = request.get_json(silent=True) or {}
    context = payload.get("context") or {}
    messages = payload.get("messages") or []
    if not isinstance(messages, list):
        return jsonify(error="messages must be a list"), 400

    def generate():
        try:
            for delta in stream_chat(context, messages):
                yield f"data: {_json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
        except (RuntimeError, ValueError) as exc:
            yield f"data: {_json.dumps({'error': str(exc)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


def _sent_occurred_at(value, business_date):
    """把页面上的触达动作固定到当前业务快照，避免混入机器当前时间。"""
    from datetime import datetime, time

    occurred_at = _parse_datetime(value, "occurred_at")
    if occurred_at is None:
        occurred_at = datetime.combine(business_date, time(hour=10))
    if occurred_at.date() != business_date:
        raise CampaignInputError("occurred_at 必须位于当前业务日期")
    return occurred_at


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
        business_date = parse_business_date(payload.get("business_date"))
        if business_date != DEFAULT_BUSINESS_DATE:
            raise CampaignInputError("历史业务日期为只读快照，不能执行客户触达")
    except (CampaignInputError, ValueError) as exc:
        return jsonify(error=str(exc)), 400

    event_type = payload.get("event_type")
    try:
        if event_type == "sent":
            event = create_sent_event(
                strategy_id=str(payload.get("strategy_id", "")),
                occurred_at=_sent_occurred_at(
                    payload.get("occurred_at"), business_date
                ),
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
            business_date=parse_business_date(request.args.get("business_date")),
        )
    except (CampaignInputError, ValueError) as exc:
        return jsonify(error=str(exc)), 400
    except CampaignStoreError:
        app.logger.exception("Campaign event query failed")
        return jsonify(error="campaign events are temporarily unavailable"), 503
    return jsonify(events=events)


@app.post("/campaign/demo-holdings")
def campaign_demo_holding_create():
    """演示入口：模拟新增持仓，自动归因后驱动响应 KPI。"""
    try:
        payload = _campaign_event_payload()
        business_date = parse_business_date(payload.get("business_date"))
        if business_date != DEFAULT_BUSINESS_DATE:
            raise CampaignInputError("历史业务日期为只读快照，不能模拟新增持仓")
        amount = payload.get("amount", 50_000)
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            raise CampaignInputError("amount must be a number")
        result = simulate_holding_purchase(
            customer_id=str(payload.get("customer_id", "")),
            product_id=str(payload.get("product_id", "")),
            buy_date=_parse_date(payload.get("buy_date"), "buy_date"),
            amount=float(amount),
            window_days=int(payload.get("window_days", 30)),
            business_date=business_date,
        )
    except CampaignInputError as exc:
        return jsonify(error=str(exc)), 422
    except (ValueError, TypeError) as exc:
        return jsonify(error=f"参数不合法：{exc}"), 422
    except CampaignStoreError:
        app.logger.exception("Demo holding simulation failed")
        return jsonify(error="simulated holding could not be recorded"), 503
    return jsonify(result), 201


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
                keyword=request.args.get("keyword"),
                contact_date=request.args.get("contact_date"),
            )
        )
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 503


@app.get("/marketing/tasks")
def marketing_tasks():
    """客户经理全量客户机会队列；策略与机会分均读取最新ADS日批。"""
    try:
        return jsonify(
            query_marketing_tasks(
                page=int(request.args.get("page", 1)),
                size=int(request.args.get("size", 20)),
                status=request.args.get("status", "all"),
                keyword=request.args.get("keyword"),
                cohort=request.args.get("cohort", "all"),
                workspace=request.args.get("workspace", "all"),
                manager_view=request.args.get("manager_view", "today"),
                manager_daily_capacity=int(
                    request.args.get(
                        "manager_daily_capacity", DEFAULT_MANAGER_DAILY_CAPACITY
                    )
                ),
                business_date=parse_business_date(request.args.get("business_date")),
            )
        )
    except (ValueError, TypeError) as exc:
        return jsonify(error=str(exc)), 400
    except MarketingTaskStoreError:
        app.logger.exception("Marketing task query failed")
        return jsonify(error="marketing tasks are temporarily unavailable"), 503


@app.get("/customers/<customer_id>/strategies")
def customer_strategy_list(customer_id: str):
    """客户Top3：只读取最新ADS营销日批结果。"""
    try:
        business_date = parse_business_date(request.args.get("business_date"))
        return jsonify(customer_strategies(customer_id, business_date))
    except CampaignInputError as exc:
        return jsonify(error=str(exc)), 404
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except OSError as exc:
        app.logger.exception("Customer strategies query failed")
        return jsonify(error=f"customer strategies failed: {exc}"), 503
    except CampaignStoreError:
        app.logger.exception("Customer strategies query failed")
        return jsonify(error="customer strategies are temporarily unavailable"), 503


@app.post("/marketing/response/predict")
def marketing_response_predict():
    """使用DWD历史与队友A1模型完成单客户/产品/渠道在线预测。"""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="request body must be a JSON object"), 400
    try:
        return jsonify(get_mysql_predictor().predict_dict(payload))
    except (FeatureAssemblyError, ValueError) as exc:
        return jsonify(error=str(exc)), 400
    except (ImportError, FileNotFoundError, OSError, RuntimeError):
        app.logger.exception("A1 online prediction failed")
        return jsonify(error="A1 prediction service is temporarily unavailable"), 503


@app.post("/marketing/strategy/generate")
def marketing_strategy_generate():
    """运营试算：单客户A1排序+基础规则过滤，不覆盖ADS日批。"""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="request body must be a JSON object"), 400
    try:
        manager_pool_size = int(
            payload.get("manager_pool_size", DEFAULT_MANAGER_POOL_SIZE)
        )
        manager_daily_capacity = int(
            payload.get(
                "manager_daily_capacity", DEFAULT_MANAGER_DAILY_CAPACITY
            )
        )
        top_n = int(payload.get("top_n", DEFAULT_TOP_N))
        if not 1 <= top_n <= 3:
            raise ValueError("top_n must be between 1 and 3")
        customer_id = str(payload.get("customer_id", ""))
        business_date = parse_business_date(payload.get("business_date"))
        disabled_constraints = payload.get("disabled_constraints", [])
        if not isinstance(disabled_constraints, list):
            raise ValueError("disabled_constraints must be an array of rule ids")
        return jsonify(
            generate_customer_strategy(
                customer_id,
                manager_pool_size=manager_pool_size,
                manager_daily_capacity=manager_daily_capacity,
                top_n=top_n,
                disabled_constraints=disabled_constraints,
                response_predictor=get_mysql_predictor(),
                strategy_date=business_date,
            )
        )
    except StrategyGenerationError as exc:
        return jsonify(error=str(exc)), 404
    except (ValueError, TypeError) as exc:
        return jsonify(error=f"参数不合法：{exc}"), 400
    except (ImportError, FileNotFoundError, OSError, RuntimeError):
        app.logger.exception("A1-backed strategy generation failed")
        return jsonify(error="A1 prediction service is temporarily unavailable"), 503


@app.get("/marketing/rules")
def marketing_rules():
    """规则引擎元数据（Tab2 轨迹区块的规则清单）。"""
    return jsonify(rules=build_default_engine().metadata())


@app.get("/dashboard/summary")
def dashboard_summary_endpoint():
    """Tab4 看板聚合：模型指标 + 分布 + 漏斗 + KPI + 数据分层行数。"""
    try:
        business_date = parse_business_date(request.args.get("business_date"))
        return jsonify(dashboard_summary(business_date))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except (OSError, KeyError):
        app.logger.exception("Dashboard summary failed")
        return jsonify(error="dashboard summary is temporarily unavailable"), 503


@app.get("/pipeline/runs/latest")
def pipeline_run_latest():
    """返回固定业务日批DAG与本进程最近一次运行状态。"""
    return jsonify(
        definition=pipeline_definition(),
        run=latest_pipeline_run(),
    )


@app.post("/pipeline/runs")
def pipeline_run_create():
    """按业务日期触发受控日批；不接受命令、路径等任意执行参数。"""
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return jsonify(error="请求体必须是 JSON 对象"), 400
    try:
        business_date = parse_business_date(payload.get("business_date"))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    try:
        run = start_pipeline_run(business_date)
    except PipelineBusyError as exc:
        return jsonify(error=str(exc)), 409
    return jsonify(run=run), 202


def main() -> None:
    app.run(host="0.0.0.0", port=5001)


if __name__ == "__main__":
    main()
