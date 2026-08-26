# 前端接入契约（Frontend API Contract）

> 给前端同学的对接文档：6 个接口 + 请求/响应样例。前端只通过 Flask API 取数，不直连 MySQL、不读 CSV。
> 服务地址：后端 `http://127.0.0.1:5001`（已开 CORS，前端 dev 端口 3000 可直接 fetch）。

## 接口总览

| # | 方法与路径 | 前端位置（page.tsx 硬编码处） |
|---|-----------|------------------------------|
| 1 | `GET /customers/<id>/profile` | 客户档案详情抽屉 |
| 2 | `GET /portfolio/scenarios` + `POST /portfolio/optimize` | 智能投顾：场景参数面板、配置结果、约束检查 |
| 3 | `GET /marketing/roster` | 营销运营 A1：响应名单表 |
| 4 | `GET /customers/<id>/strategies` | 营销运营 A2：Top3 策略卡 + 推荐依据 |
| 5 | `POST /campaign/events` | 执行追踪：已触达 / 记录响应 / 标记购买 按钮 |
| 6 | `GET /dashboard/summary` | 经营看板：全部 KPI 与图表 |

---

## 1. GET /customers/C000010/profile

```json
{
  "customer_id": "C000010", "age_group": "35-44", "city": "南京",
  "occupation": "企业职员", "income_level": "10-30万", "register_date": "2021-01-02",
  "aum": 123456.78, "risk_appetite": "R2", "vip_level": "普通", "has_app": 1,
  "holding_product_count": 2, "holding_amount": 98000.0,
  "event_count": 12, "login_count": 9, "consult_count": 2, "complaint_count": 1,
  "campaign_count": 5, "response_count": 2, "response_rate": 0.4,
  "last_contact_date": "2026-03-28"
}
```

## 2. GET /portfolio/scenarios

```json
{ "scenarios": [ { "scenario_id": "S01", "scenario_name": "官方场景 S01",
  "scenario_type": "preset", "total_amount": 500000.0, "risk_aversion": 0.94,
  "max_single_weight": 0.3, "max_high_risk_weight": 0.5,
  "min_liquid_weight": 0.2, "min_holdings": 4 }, ... ] }
```

### POST /portfolio/optimize（请求 = 场景参数；响应 = 配置结果）

```json
// 请求
{ "total_amount": 500000, "risk_aversion": 0.94, "max_single_weight": 0.3,
  "max_high_risk_weight": 0.5, "min_liquid_weight": 0.2, "min_holdings": 4 }
```

```json
// 响应（节选）
{ "summary": { "utility": 0.038174573187, "expected_return": 0.0526,
  "portfolio_volatility": 0.0418, "cash_weight": 0.15,
  "holdings_count": 17, "high_risk_weight": 0.30,
  "liquid_plus_cash": 0.50, "optimality_gap": 0.0 },
  "allocations": [ { "product_id": "P001", "product_name": "...",
    "risk_level": "R2", "weight": 0.24, "amount": 120000.0 }, ... ] }
```

> 前端"流动性滑杆联动重算"目前是假算（`8 + (liquidity-20)/5`），改为调本接口：滑杆值 = `min_liquid_weight`（÷100），其余参数读场景。

## 3. GET /marketing/roster?page=1&size=50&sort=prob_desc

```json
{ "total": 8000, "page": 1, "size": 50,
  "customers": [ { "contact_id": "KT000000", "customer_id": "C000830",
    "product_id": "P004", "channel": "manager", "contact_date": "2026-04-15",
    "response_prob": 0.989039 }, ... ] }
```

参数：`page`/`size`（≤200）、`sort`（prob_desc|contact_id）、`channel`（sms/call/app_push/manager）、`min_prob`（0~1）。

## 4. GET /customers/C000010/strategies

```json
{ "customer_id": "C000010", "strategy_date": "2026-04-15", "risk_appetite": "R2",
  "items": [ { "strategy_id": "C000010:1", "rank": 1, "product_id": "P012",
    "product_name": "混合012号", "recommended_channel": "manager",
    "recommended_time": "工作日09:00-12:00",
    "marketing_script": "尊敬的普通客户，基于您的风险偏好R2……",
    "status": "待执行",
    "rule_trace": [ { "rule_id": "risk_match", "passed": true,
      "reason": "产品风险等级在客户偏好范围内" }, ... ] } ] }
```

- `status` ∈ 待执行 / 已触达 / 已响应（由事件表推导）
- `rule_trace` 是"推荐依据"区块的数据源：9 条规则的命中/拦截原因，逐条展示即可（合规性验收点）

## 5. POST /campaign/events

```json
// 标记已触达
{ "event_type": "sent", "strategy_id": "C000010:1" }

// 记录响应（购买事实，过归因校验；窗口默认策略日+30天，可用 window_days 覆盖）
{ "event_type": "responded", "customer_id": "C000010", "product_id": "P012",
  "buy_date": "2026-04-20", "amount": 50000 }
```

```json
// 成功（201）
{ "campaign_event_id": 2, "strategy_id": "C000010:1", "event_type": "responded",
  "occurred_at": "2026-08-26T10:43:58", "product_id": "P012", "amount": 50000.0,
  "attribution": "命中 Top3 第 1 位，窗口内购买，归因成功", "rank": 1 }

// 失败（422，error 直接展示给评委看——归因边界演示）
{ "error": "购买日期 2026-07-01 超出归因窗口（2026-04-15 +30 天= 2026-05-15），不归因" }
```

## 6. GET /dashboard/summary

```json
{ "model_metrics": { "auc": 0.8618686098, "best_f1": 0.5950288727,
    "lift_at_10_percent": 3.7375647707 },
  "prediction_stats": { "total": 8000, "mean_prob": 0.1957,
    "high_intent": 476, "mid_intent": 1398, "low_intent": 6126 },
  "strategy_stats": { "rows": 6000, "customers": 2000,
    "channel_distribution": { "manager": 5136, "app_push": 642, "sms": 222 },
    "time_distribution": { "工作日09:00-12:00": 1560, ... } },
  "partb_stats": { "scenarios": 20, "total_utility": 0.61122985667 },
  "funnel": { "stages": [ { "stage": "策略生成", "count": 6000 },
      { "stage": "已触达", "count": 0 }, { "stage": "已响应", "count": 0 } ],
    "pending": 6000 },
  "kpis": [ { "kpi_id": "manager_conversion",
      "label": "客户经理 MGR001 4月转化数", "target": 30, "actual": 0,
      "completion_rate": 0.0, "unit": "个" },
    { "kpi_id": "manager_response_rate", "label": "manager 渠道响应率",
      "target": 0.25, "actual": 0.0, "completion_rate": 0.0, "unit": "%" },
    { "kpi_id": "campaign_touch_progress", "label": "活动触达进度",
      "target": 0.6, "actual": 0.0, "completion_rate": 0.0, "unit": "%" } ],
  "data_layers": { "ods": 79751, "dwd": 79751, "dws": 8000, "ads": 8020 } }
```

---

## 联调约定

1. **后端启动**：`python -m src.app`（5001 端口）；**前端启动**：`cd frontend && npm run dev`（3000 端口）。CORS 已开，直接 fetch `http://127.0.0.1:5001/...` 即可（建议把 base 地址做成一个常量，演示时改成同机地址）。
2. **状态流转**：执行追踪按钮接 #5，按钮点击后重新拉 #4 刷新 status；看板数字拉 #6 刷新。
3. **错误展示**：422 的 `error` 字段是给评委看的中文原因，前端直接 toast/红字展示，不要吞掉。
4. 演示数据（22 个 responded + 一批 sent）由后端预置，前端不用管初始数字。

## 已知差异（联调时注意）

- 队友版策略文件的渠道分布（manager 5136）与引擎配额口径（600）不同——#4/#6 返回的是**当前提交文件**的真实数据，前端直接渲染即可。
- 轨迹校验发现队友版话术缺"投资须谨慎"字样（`script_compliance_note` 未通过）——前端如实展示红/绿即可，这正是合规性验收的演示点；是否改话术由组内会后定。
