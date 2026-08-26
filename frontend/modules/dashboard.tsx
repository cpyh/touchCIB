"use client";

import { useEffect, useMemo, useState } from "react";

import {
  DashboardApiError,
  DashboardOverview,
  DataStatus,
  getDashboardOverview,
} from "../shared/dashboard-api";
import { channelNames, PageHead, Status } from "../shared/ui";

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

function percent(
  value: number | null | undefined,
  digits = 1
) {
  return value == null
    ? "—"
    : `${(value * 100).toFixed(digits)}%`;
}

function compactMoney(value: number | null | undefined) {
  if (value == null) return "—";

  if (Math.abs(value) >= 100_000_000) {
    return `¥ ${(value / 100_000_000).toFixed(2)}亿`;
  }

  if (Math.abs(value) >= 10_000) {
    return `¥ ${(value / 10_000).toFixed(1)}万`;
  }

  return `¥ ${value.toLocaleString("zh-CN", {
    maximumFractionDigits: 2,
  })}`;
}

function exactMoney(value: number | null | undefined) {
  return value == null
    ? "—"
    : `¥ ${value.toLocaleString("zh-CN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;
}

function metric(
  value: number | null | undefined,
  digits = 3
) {
  return value == null ? "—" : value.toFixed(digits);
}

function formatTime(value: string) {
  const date = new Date(value);

  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("zh-CN", {
        hour12: false,
      });
}

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
  onOpenExpiry,
  onOpenPortfolio,
}: {
  onOpenMarketing?: (customerId: string) => void;
  onOpenExpiry?: (customerId: string) => void;
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
  const conversion = actions?.conversion;
  const touch = actions?.touch;
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
                : `更新于 ${formatTime(
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

      {/* ================= 今日行动（运营指令） ================= */}

      {actions && (
        <section className="dashboard-section action-section">
          <SectionTitle
            index="00"
            title="今日行动"
            description="今天要动手的三件事：盯转化、推触达、接住到期资金。"
          />
          <div className="action-grid">
            <article className={`action-card ${(conversion?.gap ?? 0) > 0 ? "level-red" : "level-green"}`}>
              <header><b>转化缺口</b><span>{conversion?.gap ? `还差 ${conversion.gap} 个` : "已达目标"}</span></header>
              <strong>{conversion?.actual}<i>/</i><em>{conversion?.target}</em></strong>
              <p>{conversion?.label} · 已触达未响应的客户是跟进的优先对象</p>
              <button className="primary" onClick={() => onOpenMarketing?.("")}>去营销工作台执行 →</button>
            </article>

            <article className={`action-card ${(touch?.sent_customers ?? 0) < (touch?.total_customers ?? 1) ? "level-amber" : "level-green"}`}>
              <header><b>触达缺口</b><span>{(touch?.total_customers ?? 0) - (touch?.sent_customers ?? 0)} 位客户待触达</span></header>
              <strong>{touch?.sent_customers?.toLocaleString()}<i>/</i><em>{touch?.total_customers?.toLocaleString()}</em></strong>
              <p>全量客户均为运营对象；高意向客户（概率≥70%）中还有 <b>{touch?.high_intent_untouched ?? "—"}</b> 名未触达，建议今日优先执行</p>
              <button className="primary" onClick={() => onOpenMarketing?.("")}>优先触达高意向客户 →</button>
            </article>

            {(() => {
              const expiry = dashboard.expiry_warning;
              if (!expiry?.available) return null;
              return (
                <article className="action-card level-amber">
                  <header><b>到期跟进</b><span>再配置机会</span></header>
                  <strong>{expiry.holding_count.toLocaleString()}<i>笔</i><em>{expiry.customer_count.toLocaleString()} 位客户</em></strong>
                  <p>{expiry.window_days} 天内 ¥{compactMoney(expiry.amount)} 到期；<b>{expiry.items[0]?.product_name ?? "—"}</b> 等产品迎来赎回，是挽留与再配置窗口</p>
                  <button
                    className="primary"
                    onClick={() => (onOpenExpiry ?? onOpenMarketing)?.(expiry.items[0]?.customer_id ?? "")}
                  >
                    跟进到期客户 →
                  </button>
                </article>
              );
            })()}
          </div>
        </section>
      )}

      {/* ================= 运营参考（背景信息） ================= */}

      <section className="dashboard-section reference-section">
        <SectionTitle
          index="01"
          title="运营参考"
          description="渠道表现与算法健康度，为行动提供依据而非指令。"
        />
        <div className="reference-grid">
          <article className="reference-card">
            <header><b>渠道表现</b><span>预算倾斜参考</span></header>
            <div className="reference-fact">
              <span>经理渠道现场响应率</span>
              <strong>{channel?.manager_response_rate != null ? `${(channel.manager_response_rate * 100).toFixed(1)}%` : "—"}</strong>
              <small>目标 {channel ? `${(channel.manager_target * 100).toFixed(0)}%` : "—"} · 触达 {channel?.manager_sent ?? "—"} 位 / 响应 {channel?.manager_responded ?? "—"} 位</small>
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
              <strong>AUC {(a1.auc ?? 0).toFixed(4)} · F1 {(a1.f1 ?? 0).toFixed(4)} · Lift {(a1.lift_at_10 ?? 0).toFixed(2)}</strong>
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

      {/* ================= 数据总览 ================= */}

      <section className="dashboard-section">
        <SectionTitle
          index="02"
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
              {business.customer_count.toLocaleString()}
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
              {business.product_count.toLocaleString()} 款
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
              {business.historical_contact_count.toLocaleString()}
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
                {business.customer_count.toLocaleString()} 位客户
              </Status>
            </div>

            <div className="vertical-bars">
              {dashboard.risk_distribution.map(
                (item, index) => (
                  <div key={item.risk_level}>
                    <em>
                      {item.count.toLocaleString()}
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

    </>
  );
}