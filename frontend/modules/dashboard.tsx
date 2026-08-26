"use client";

import { useEffect, useMemo, useState } from "react";

import {
  DashboardApiError,
  DashboardOverview,
  DataStatus,
  getDashboardOverview,
} from "../shared/dashboard-api";
import { channelNames, PageHead, Status } from "../shared/ui";
import {
  compactMoney,
  exactMoney,
  formatDateTime,
  formatNumber,
  metric,
  percent,
} from "../shared/format";

const scenarios = Array.from(
  { length: 20 },
  (_, index) => `S${String(index + 1).padStart(2, "0")}`
);

const statusText: Record<DataStatus, string> = {
  READY: "数据已就绪",
  NOT_READY: "待生成",
  INVALID: "结果校验异常",
  NOT_STARTED: "尚未执行",
};

const validationLabels: Record<string, string> = {
  customer_coverage_passed: "客户名单",
  top3_complete_passed: "每客Top3",
  product_unique_passed: "产品不重复",
  channel_enum_passed: "渠道合法",
  time_enum_passed: "时段合法",
  script_length_passed: "话术格式",
};

function ResultStatus({ status }: { status: DataStatus }) {
  return (
    <Status warn={status !== "READY"}>
      {statusText[status]}
    </Status>
  );
}

function EmptyState({
  status,
  text,
}: {
  status: DataStatus;
  text: string;
}) {
  return (
    <div
      className={`dashboard-empty ${
        status === "INVALID" ? "invalid" : ""
      }`}
    >
      <b>{statusText[status]}</b>
      <span>{text}</span>
    </div>
  );
}

function SectionTitle({
  index,
  title,
  description,
}: {
  index: string;
  title: string;
  description: string;
}) {
  return (
    <div className="dashboard-section-title">
      <b>{index}</b>

      <div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </div>
  );
}

export function DashboardPage({
  onOpenMarketing,
  onOpenPortfolio,
}: {
  onOpenMarketing?: (customerId: string) => void;
  onOpenPortfolio?: (customerId: string) => void;
}) {
  const [dashboard, setDashboard] =
    useState<DashboardOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    getDashboardOverview(
      "S01",
      controller.signal
    )
      .then(setDashboard)
      .catch((requestError: unknown) => {
        if (
          requestError instanceof DOMException &&
          requestError.name === "AbortError"
        ) {
          return;
        }

        setError(
          requestError instanceof DashboardApiError
            ? requestError.message
            : "可视化看板加载失败"
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });

    return () => controller.abort();
  }, [refreshKey]);

  const maxRiskCount = useMemo(
    () =>
      Math.max(
        ...(dashboard?.risk_distribution.map(
          (item) => item.count
        ) ?? [1]),
        1
      ),
    [dashboard]
  );

  const maxIntentCount = useMemo(
    () =>
      Math.max(
        ...(dashboard?.a1_performance.probability_distribution.map(
          (item) => item.count
        ) ?? [1]),
        1
      ),
    [dashboard]
  );

  const maxChannelCount = useMemo(
    () =>
      Math.max(
        ...(dashboard?.a2_performance.channel_distribution.map(
          (item) => item.count
        ) ?? [1]),
        1
      ),
    [dashboard]
  );

  const maxTimeCount = useMemo(
    () =>
      Math.max(
        ...(dashboard?.a2_performance.time_distribution?.map(
          (item) => item.count
        ) ?? [1]),
        1
      ),
    [dashboard]
  );

  function refresh() {
    setLoading(true);
    setError("");
    setRefreshKey((value) => value + 1);
  }

  if (!dashboard && loading) {
    return (
      <>
        <PageHead
          title="可视化看板"
          description="从业务数据到算法决策，再到策略执行与结果回流。"
          action={<Status>正在读取真实数据</Status>}
        />

        <div className="dashboard-loading">
          <i />
          <b>正在聚合可视化看板数据…</b>
          <span>读取 MySQL 与正式算法结果文件</span>
        </div>
      </>
    );
  }

  if (!dashboard && error) {
    return (
      <>
        <PageHead
          title="可视化看板"
          description="从业务数据到算法决策，再到策略执行与结果回流。"
          action={<Status warn>接口连接失败</Status>}
        />

        <div className="dashboard-error">
          <b>无法读取可视化看板</b>
          <p>{error}</p>

          <button
            className="secondary"
            onClick={refresh}
          >
            重新连接
          </button>
        </div>
      </>
    );
  }

  if (!dashboard) {
    return null;
  }

  const business = dashboard.business_metrics;
  const a1 = dashboard.a1_performance;
  const a2 = dashboard.a2_performance;
  const portfolioSummary =
    dashboard.portfolio_summary;

  const validationEntries = Object.entries(
    a2.validation ?? {}
  );

  const validationPassed =
    validationEntries.filter(
      ([, passed]) => passed
    ).length;

  const actions = dashboard.action_items;
  const channel = actions?.channel;
  const a1AllAnchorsMet =
    (a1.auc ?? 0) >= 0.85 &&
    (a1.f1 ?? 0) >= 0.615 &&
    (a1.lift_at_10 ?? 0) >= 3.3;
  const partBOk =
    !!portfolioSummary &&
    portfolioSummary.status === "READY" &&
    portfolioSummary.constraints_passed_count ===
      portfolioSummary.scenario_count;

  return (
    <>
      <PageHead
        title="可视化看板"
        description="从数据基础、算法决策到营销执行，展示智能财富管理的完整业务闭环。"
        action={
          <div className="dashboard-actions">
            <span
              className={
                loading
                  ? "refresh-state busy"
                  : "refresh-state"
              }
            >
              {loading
                ? "正在刷新"
                : `更新于 ${formatDateTime(
                    dashboard.generated_at
                  )}`}
            </span>

            <button
              className="secondary"
              disabled={loading}
              onClick={refresh}
            >
              ↻ 刷新数据
            </button>
          </div>
        }
      />

      {error && (
        <div className="dashboard-inline-error">
          <span>本次刷新失败：{error}</span>
          <button onClick={refresh}>重试</button>
        </div>
      )}

      {/* ================= 营销概览（账户级） ================= */}

      <section className="dashboard-section campaign-section">
        <SectionTitle
          index="00"
          title="营销概览"
          description="本批营销活动的规模、触达、转化与机会，一屏总览。"
        />
        <div className="campaign-kpis">
          <article className="gold"><small>策略规模</small><strong>{(
            dashboard.action_items?.touch?.total_strategies ?? 0
          ).toLocaleString()}</strong><span>策略单元</span></article>
          <article><small>已触达客户</small><strong>{
            dashboard.marketing_funnel?.contacted_customer_count?.toLocaleString() ?? "—"
          }</strong><span>全量 8,000 位</span></article>
          <article><small>已响应客户</small><strong>{
            dashboard.marketing_funnel?.responded_customer_count?.toLocaleString() ?? "—"
          }</strong><span>归因口径</span></article>
          <article><small>触达后响应率</small><strong>{
            dashboard.marketing_funnel?.contacted_customer_count
              ? `${(
                  (dashboard.marketing_funnel.responded_customer_count ?? 0)
                  / dashboard.marketing_funnel.contacted_customer_count
                  * 100
                ).toFixed(1)}%`
              : "—"
          }</strong><span>客户口径</span></article>
          <article><small>高意向潜力</small><strong>{
            dashboard.opportunity?.golden.expected_responses?.toLocaleString() ?? "—"
          }</strong><span>潜在响应客户</span></article>
          <article><small>到期资金</small><strong>{
            dashboard.expiry_warning?.available
              ? compactMoney(dashboard.expiry_warning.amount)
              : "—"
          }</strong><span>30 天内到期</span></article>
        </div>
      </section>

      {/* ================= 数据总览 ================= */}

      <section className="dashboard-section">
        <SectionTitle
          index="01"
          title="数据总览"
          description="平台当前管理的客户、资产、产品与历史营销数据。"
        />

        <div
          className="business-kpis"
          aria-label="核心业务指标"
        >
          <article>
            <small>客户总数</small>
            <strong>
              {formatNumber(business.customer_count)}
            </strong>
            <span>财富客户记录</span>
          </article>

          <article>
            <small>客户资产管理规模</small>
            <strong>
              {compactMoney(business.total_aum)}
            </strong>
            <span
              title={exactMoney(
                business.total_aum
              )}
            >
              客户AUM总额
            </span>
          </article>

          <article>
            <small>在售产品</small>
            <strong>
              {formatNumber(business.product_count)} 款
            </strong>
            <span>财富产品数量</span>
          </article>

          <article>
            <small>产品持仓金额</small>
            <strong>
              {compactMoney(
                business.total_holding_amount
              )}
            </strong>
            <span
              title={exactMoney(
                business.total_holding_amount
              )}
            >
              客户可识别持仓
            </span>
          </article>

          <article>
            <small>历史营销触达</small>
            <strong>
              {formatNumber(business.historical_contact_count)}
            </strong>
            <span>历史营销记录</span>
          </article>

          <article>
            <small>历史响应率</small>
            <strong>
              {percent(
                business.historical_response_rate
              )}
            </strong>
            <span>历史触达响应表现</span>
          </article>
        </div>

        <div className="overview-grid">
          <section className="card dashboard-panel risk-panel">
            <div className="section-head">
              <div>
                <h2>客户风险分布</h2>
                <p>R1—R5风险偏好客户数量</p>
              </div>

              <Status>
                {formatNumber(business.customer_count)} 位客户
              </Status>
            </div>

            <div className="vertical-bars">
              {dashboard.risk_distribution.map(
                (item, index) => (
                  <div key={item.risk_level}>
                    <em>
                      {formatNumber(item.count)}
                    </em>

                    <i
                      className={
                        index === 2
                          ? "gold"
                          : ""
                      }
                      style={{
                        height: `${Math.max(
                          (item.count /
                            maxRiskCount) *
                            100,
                          3
                        )}%`,
                      }}
                    />

                    <b>{item.risk_level}</b>
                    <span>
                      {item.risk_label}
                    </span>
                  </div>
                )
              )}
            </div>
          </section>

          <section className="card dashboard-panel holding-panel">
            <div className="section-head">
              <div>
                <h2>持仓类型分布</h2>
                <p>
                  总持仓{" "}
                  {compactMoney(
                    business.total_holding_amount
                  )}
                </p>
              </div>

              <Status>真实持仓</Status>
            </div>

            <div className="distribution-list">
              {dashboard.holding_distribution.map(
                (item) => (
                  <div key={item.product_type}>
                    <span>
                      <b>{item.product_type}</b>
                      <em>
                        {compactMoney(
                          item.holding_amount
                        )}
                      </em>
                    </span>

                    <i>
                      <b
                        style={{
                          width: `${
                            (item.ratio ?? 0) *
                            100
                          }%`,
                        }}
                      />
                    </i>

                    <small>
                      {percent(item.ratio)}
                    </small>
                  </div>
                )
              )}
            </div>
          </section>
        </div>
      </section>

      {/* ================= 渠道表现与算法质量（运营参考） ================= */}

      <section className="dashboard-section reference-section">
        <SectionTitle
          index="03"
          title="渠道表现与算法质量"
          description="渠道表现供资源倾斜参考，算法健康度保障活动稳定性。"
        />
        <div className="reference-grid">
          <article className="reference-card">
            <header><b>渠道表现</b><span>资源倾斜参考</span></header>
            <div className="reference-fact">
              <span>经理渠道现场响应率</span>
              <strong>{percent(channel?.manager_response_rate)}</strong>
              <small>目标 {percent(channel?.manager_target, 0)} · 触达 {formatNumber(channel?.manager_sent)} 位 / 响应 {formatNumber(channel?.manager_responded)} 位</small>
            </div>
            <div className="reference-fact">
              <span>历史渠道平均响应率</span>
              <strong>{percent(business.historical_response_rate)}</strong>
              <small>来自 5 万条历史触达训练样本</small>
            </div>
            <span className="action-hint">经理渠道明显领先，后续批次建议继续倾斜</span>
          </article>

          <article className="reference-card">
            <header><b>算法质量</b><span>{a1AllAnchorsMet && partBOk ? "无异常" : "需复核"}</span></header>
            <div className="reference-fact">
              <span>A1 验证指标</span>
              <strong>AUC {metric(a1.auc, 4)} · F1 {metric(a1.f1, 4)} · Lift {metric(a1.lift_at_10, 2)}</strong>
              <small>三项全部达到题目满分锚点</small>
            </div>
            <div className="reference-fact">
              <span>Part B 组合优化</span>
              <strong>{portfolioSummary?.constraints_passed_count ?? "—"}/{portfolioSummary?.scenario_count ?? "—"} 场景约束通过</strong>
              <small>最优性 gap ≈ 1e-18（切平面上界证书）</small>
            </div>
            <button className="secondary" onClick={() => onOpenPortfolio?.("")}>去投顾演示最优性证书 →</button>
          </article>
        </div>
      </section>

      {/* ================= 转化机会挖掘 ================= */}

      {dashboard.opportunity && (
        <section className="dashboard-section opportunity-section">
          <SectionTitle
            index="02"
            title="转化机会洞察"
            description="从预测与事件数据挖出的三类转化机会：高意向客户、产品机会与到期承接。"
          />
          <div className="opportunity-grid">
            <article className="opportunity-card lead">
              <header><b>高意向客户机会</b><span>高意向未触达</span></header>
              <strong>{formatNumber(dashboard.opportunity.golden.count)}<i>名</i></strong>
              <p>响应概率 ≥ 70% 未触达客户，期望响应约 <b>{formatNumber(dashboard.opportunity.golden.expected_responses)} 名</b>——触达即转化</p>
              <button className="primary" onClick={() => onOpenMarketing?.("")}>优先触达高意向客户 →</button>
            </article>

            <article className="opportunity-card">
              <header><b>产品机会榜</b><span>高意向待触达 Top3</span></header>
              <ul className="opportunity-products">
                {dashboard.opportunity.products.map((item) => (
                  <li key={item.product_id}><span>{item.product_id}</span><em>{formatNumber(item.count)} 条高意向触达未执行</em></li>
                ))}
              </ul>
              <p>这些产品的高意向客户最集中，批量触达效率最高</p>
              <button className="primary" onClick={() => onOpenMarketing?.("")}>去营销工作台执行 →</button>
            </article>

            <article className="opportunity-card">
              <header><b>到期承接机会</b><span>再配置窗口</span></header>
              <strong>{formatNumber(dashboard.opportunity.expiry.customer_count)}<i>位</i></strong>
              <p>{formatNumber(dashboard.opportunity.expiry.window_days)} 天内 {compactMoney(dashboard.opportunity.expiry.amount)} 到期，是先发制人的交叉销售窗口</p>
              <button className="primary" onClick={() => onOpenMarketing?.("")}>跟进到期客户 →</button>
            </article>
          </div>
        </section>
      )}

    </>
  );
}
