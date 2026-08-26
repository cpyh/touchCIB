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
  onOpenPortfolio,
}: {
  onOpenMarketing?: (customerId: string) => void;
  onOpenPortfolio?: (customerId: string) => void;
}) {
  const [scenarioId, setScenarioId] = useState("S01");
  const [dashboard, setDashboard] =
    useState<DashboardOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    getDashboardOverview(
      scenarioId,
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
  }, [scenarioId, refreshKey]);

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

  function selectScenario(nextScenario: string) {
    if (nextScenario === scenarioId) {
      return;
    }

    setScenarioId(nextScenario);
    setLoading(true);
    setError("");
  }

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
  const portfolio = dashboard.portfolio;
  const portfolioSummary =
    dashboard.portfolio_summary;
  const funnel = dashboard.marketing_funnel;

  const strategyCount =
    funnel.generated_strategy_count ??
    a2.result_row_count ??
    a2.generated_customer_count * 3;

  const sentCount =
    funnel.sent_strategy_count ?? 0;

  const respondedCount =
    funnel.responded_strategy_count ?? 0;

  const pendingCount = Math.max(
    0,
    strategyCount - sentCount
  );

  const touchRate =
    strategyCount > 0
      ? sentCount / strategyCount
      : null;

  const responseRate =
    sentCount > 0
      ? respondedCount / sentCount
      : null;

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
            description="目标-实际-缺口：看板发现异常，点击卡片直接跳转工作台执行。"
          />
          <div className="action-grid">
            <article className={`action-card ${(conversion?.gap ?? 0) > 0 ? "level-red" : "level-green"}`}>
              <header><b>转化缺口</b><span>{conversion?.gap ? `还差 ${conversion.gap} 个` : "已达目标"}</span></header>
              <strong>{conversion?.actual}<i>/</i><em>{conversion?.target}</em></strong>
              <p>{conversion?.label} · 已触达未响应的客户是跟进的优先对象</p>
              <button className="primary" onClick={() => onOpenMarketing?.("")}>去营销工作台执行 →</button>
            </article>

            <article className={`action-card ${(touch?.sent_strategies ?? 0) < (touch?.total_strategies ?? 1) ? "level-amber" : "level-green"}`}>
              <header><b>触达缺口</b><span>{(touch?.total_strategies ?? 0) - (touch?.sent_strategies ?? 0)} 条策略待触达</span></header>
              <strong>{touch?.sent_strategies?.toLocaleString()}<i>/</i><em>{touch?.total_strategies?.toLocaleString()}</em></strong>
              <p>高意向客户（概率≥70%）中还有 <b>{touch?.high_intent_untouched ?? "—"}</b> 名未触达，建议今日优先执行</p>
              <button className="primary" onClick={() => onOpenMarketing?.("")}>优先触达高意向客户 →</button>
            </article>

            <article className={`action-card ${(channel?.manager_response_rate ?? 0) >= (channel?.manager_target ?? 1) ? "level-green" : "level-amber"}`}>
              <header><b>渠道机会</b><span>预算倾斜建议</span></header>
              <strong>{channel?.manager_response_rate != null ? `${(channel.manager_response_rate * 100).toFixed(1)}%` : "—"}<i>vs</i><em>{channel ? `${(channel.manager_target * 100).toFixed(0)}%` : "—"}</em></strong>
              <p>经理渠道现场响应率对比历史均值 {percent(business.historical_response_rate)}，表现领先则继续倾斜经理渠道</p>
              <span className="action-hint">数据引用 · 无需跳转</span>
            </article>

            <article className={`action-card ${a1AllAnchorsMet && partBOk ? "level-green" : "level-amber"}`}>
              <header><b>算法质量</b><span>{a1AllAnchorsMet && partBOk ? "无异常" : "需复核"}</span></header>
              <strong>{a1AllAnchorsMet ? "达标" : "复核"}<i>A1</i><em>{partBOk ? "达标" : "复核"} PartB</em></strong>
              <p>AUC {(a1.auc ?? 0).toFixed(4)} · F1 {(a1.f1 ?? 0).toFixed(4)} · Lift {(a1.lift_at_10 ?? 0).toFixed(2)}；Part B {portfolioSummary?.constraints_passed_count ?? "—"}/{portfolioSummary?.scenario_count ?? "—"} 场景约束通过</p>
              <span className="action-hint">模型指标实时取自验证文件</span>
            </article>
          </div>
        </section>
      )}

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

      {/* ================= 算法分析 ================= */}

      <section className="dashboard-section">
        <SectionTitle
          index="02"
          title="A1、A2与Part B结果分析"
          description="分别验证客户识别、策略生成和资产配置三个算法环节。"
        />

        <div className="algorithm-grid">
          {/* A1 */}

          <section className="card dashboard-panel algorithm-panel">
            <div className="section-head">
              <div>
                <h2>A1 · 营销响应预测</h2>
                <p>
                  识别更可能响应的客户与产品机会
                </p>
              </div>

              <ResultStatus status={a1.status} />
            </div>

            {a1.status === "READY" ? (
              <>
                <div className="algorithm-metrics">
                  <article>
                    <small>AUC</small>
                    <strong>
                      {metric(a1.auc)}
                    </strong>
                    <span>离线验证</span>
                  </article>

                  <article>
                    <small>最优F1</small>
                    <strong>
                      {metric(a1.f1)}
                    </strong>
                    <span>阈值扫描</span>
                  </article>

                  <article>
                    <small>Lift@10%</small>
                    <strong>
                      {metric(
                        a1.lift_at_10,
                        2
                      )}
                    </strong>
                    <span>头部客户提升</span>
                  </article>

                  <article>
                    <small>预测记录</small>
                    <strong>
                      {a1.prediction_count?.toLocaleString() ??
                        "—"}
                    </strong>
                    <span>
                      平均概率{" "}
                      {percent(
                        a1.mean_probability
                      )}
                    </span>
                  </article>
                </div>

                <div className="intent-distribution">
                  <h3>预测意向分层</h3>

                  {a1.probability_distribution.map(
                    (item) => (
                      <div key={item.bucket}>
                        <span>{item.bucket}</span>

                        <i>
                          <b
                            style={{
                              width: `${
                                (item.count /
                                  maxIntentCount) *
                                100
                              }%`,
                            }}
                          />
                        </i>

                        <em>
                          {item.count.toLocaleString()}
                        </em>
                      </div>
                    )
                  )}
                </div>
              </>
            ) : (
              <EmptyState
                status={a1.status}
                text="A1验证指标或预测结果尚未准备完成。"
              />
            )}
          </section>

          {/* A2 */}

          <section className="card dashboard-panel algorithm-panel a2-panel">
            <div className="section-head">
              <div>
                <h2>A2 · Top3营销策略</h2>
                <p>
                  把预测机会转化为可执行营销动作
                </p>
              </div>

              <ResultStatus status={a2.status} />
            </div>

            {a2.status === "READY" ? (
              <>
                <div className="a2-summary">
                  <article>
                    <small>策略总数</small>
                    <strong>
                      {strategyCount.toLocaleString()}
                    </strong>
                    <span>
                      {a2.target_customer_count.toLocaleString()}
                      位客户 × Top3
                    </span>
                  </article>

                  <article>
                    <small>规则引擎</small>
                    <strong>
                      {a2.rule_count ?? "—"} 项
                    </strong>
                    <span>
                      风险、渠道、时段与话术
                    </span>
                  </article>

                  <article>
                    <small>结果校验</small>
                    <strong>
                      {validationEntries.length
                        ? `${validationPassed}/${validationEntries.length}`
                        : "—"}
                    </strong>
                    <span>
                      策略格式与完整性
                    </span>
                  </article>
                </div>

                <div className="strategy-flow">
                  <span>A1响应概率</span>
                  <i>＋</i>
                  <span>LTR学习排序</span>
                  <b>→</b>
                  <span>规则引擎</span>
                  <b>→</b>
                  <strong>
                    客户Top3策略
                  </strong>
                </div>

                <div className="a2-distributions">
                  <div>
                    <h3>推荐渠道</h3>

                    <div className="channel-distribution">
                      {a2.channel_distribution.map(
                        (item) => (
                          <div key={item.channel}>
                            <span>
                              {channelNames[
                                item.channel
                              ] ?? item.channel}
                            </span>

                            <i>
                              <b
                                style={{
                                  width: `${
                                    (item.count /
                                      maxChannelCount) *
                                    100
                                  }%`,
                                }}
                              />
                            </i>

                            <em>
                              {item.count.toLocaleString()}
                            </em>
                          </div>
                        )
                      )}
                    </div>
                  </div>

                  <div>
                    <h3>推荐时段</h3>

                    <div className="time-distribution">
                      {a2.time_distribution
                        ?.length ? (
                        a2.time_distribution.map(
                          (item) => (
                            <div
                              key={
                                item.time_slot
                              }
                            >
                              <span>
                                {
                                  item.time_slot
                                }
                              </span>

                              <i>
                                <b
                                  style={{
                                    width: `${
                                      (item.count /
                                        maxTimeCount) *
                                      100
                                    }%`,
                                  }}
                                />
                              </i>

                              <em>
                                {item.count.toLocaleString()}
                              </em>
                            </div>
                          )
                        )
                      ) : (
                        <small>
                          重启后端后读取推荐时段分布
                        </small>
                      )}
                    </div>
                  </div>
                </div>

                {validationEntries.length >
                  0 && (
                  <div className="validation-chips">
                    {validationEntries.map(
                      ([key, passed]) => (
                        <span
                          className={
                            passed
                              ? "pass"
                              : "fail"
                          }
                          key={key}
                        >
                          {passed ? "✓" : "!"}{" "}
                          {validationLabels[
                            key
                          ] ?? key}
                        </span>
                      )
                    )}
                  </div>
                )}

                <p className="metric-note">
                  HitRate@3依赖官方隐藏购买标签，当前重点展示策略生成、分布与执行合规性。
                </p>
              </>
            ) : (
              <EmptyState
                status={a2.status}
                text={
                  a2.status === "INVALID"
                    ? "策略文件未通过Top3、枚举或字段完整性校验。"
                    : "A2策略结果尚未生成。"
                }
              />
            )}
          </section>

          {/* Part B */}

          <section className="card dashboard-panel portfolio-panel full-width">
            <div className="section-head">
              <div>
                <h2>Part B · 组合配置优化</h2>
                <p>
                  验证20个场景整体结果，并支持单场景配置下钻
                </p>
              </div>

              <div className="scenario-control">
                <label htmlFor="dashboard-scenario">
                  下钻场景
                </label>

                <select
                  id="dashboard-scenario"
                  value={scenarioId}
                  disabled={loading}
                  onChange={(event) =>
                    selectScenario(
                      event.target.value
                    )
                  }
                >
                  {scenarios.map((item) => (
                    <option key={item}>
                      {item}
                    </option>
                  ))}
                </select>

                <ResultStatus
                  status={portfolio.status}
                />
              </div>
            </div>

            <div className="portfolio-total-summary">
              <article>
                <small>完成场景</small>
                <strong>
                  {portfolioSummary
                    ? `${portfolioSummary.scenario_count}/20`
                    : "—"}
                </strong>
              </article>

              <article>
                <small>约束通过</small>
                <strong>
                  {portfolioSummary
                    ? `${portfolioSummary.constraints_passed_count}/${portfolioSummary.scenario_count}`
                    : "—"}
                </strong>
              </article>

              <article>
                <small>配置明细</small>
                <strong>
                  {portfolioSummary?.allocation_row_count.toLocaleString() ??
                    "—"}{" "}
                  行
                </strong>
              </article>

              <article>
                <small>总效用</small>
                <strong>
                  {metric(
                    portfolioSummary?.total_utility,
                    6
                  )}
                </strong>
              </article>

              <article>
                <small>最大Gap</small>
                <strong>
                  {metric(
                    portfolioSummary?.max_optimality_gap,
                    8
                  )}
                </strong>
              </article>
            </div>

            {portfolio.status === "READY" ? (
              <>
                <div className="portfolio-summary">
                  <article>
                    <small>
                      {scenarioId}配置资金
                    </small>
                    <strong>
                      {compactMoney(
                        portfolio.total_amount
                      )}
                    </strong>
                  </article>

                  <article>
                    <small>预期收益率</small>
                    <strong>
                      {percent(
                        portfolio.expected_return,
                        2
                      )}
                    </strong>
                  </article>

                  <article>
                    <small>组合波动率</small>
                    <strong>
                      {percent(
                        portfolio.volatility,
                        2
                      )}
                    </strong>
                  </article>

                  <article>
                    <small>效用值</small>
                    <strong>
                      {metric(
                        portfolio.utility,
                        4
                      )}
                    </strong>
                  </article>

                  <article>
                    <small>约束审计</small>
                    <strong
                      className={
                        portfolio.constraints_satisfied
                          ? "pass"
                          : "fail"
                      }
                    >
                      {portfolio.constraints_satisfied
                        ? "全部通过"
                        : "未通过"}
                    </strong>
                  </article>
                </div>

                <div className="portfolio-details">
                  {/* 左侧 */}
                  <div className="allocation-detail">
                    <h3>按产品类型配置</h3>

                    <div className="allocation-types">
                      {portfolio.allocation_by_product_type.map(
                        (item) => (
                          <div
                            key={
                              item.product_type
                            }
                          >
                            <span>
                              {
                                item.product_type
                              }
                            </span>

                            <i>
                              <b
                                style={{
                                  width: `${
                                    item.weight *
                                    100
                                  }%`,
                                }}
                              />
                            </i>

                            <em>
                              {percent(
                                item.weight
                              )}
                            </em>
                          </div>
                        )
                      )}
                    </div>

                    <p className="portfolio-audit">
                      现金权重{" "}
                      {percent(
                        portfolio.cash_weight,
                        3
                      )}{" "}
                      · 最优性差距{" "}
                      {metric(
                        portfolio.optimality_gap,
                        6
                      )}
                    </p>
                  </div>

                  {/* 右侧 */}
                  <div className="product-detail">
                    <div className="product-detail-title">
                      <h3>产品配置明细</h3>

                      <small>
                        滚动查看全部{" "}
                        {
                          portfolio
                            .allocation_items
                            .length
                        }{" "}
                        款
                      </small>
                    </div>

                    {/* 注意：这里已经删除了原来的 table 公共 class */}
                    <div
                      className="portfolio-table"
                      tabIndex={0}
                      aria-label={`${scenarioId}产品配置明细，可滚动查看`}
                    >
                      <table>
                        <colgroup>
                          <col className="product-col" />
                          <col className="risk-col" />
                          <col className="weight-col" />
                          <col className="money-col" />
                        </colgroup>

                        <thead>
                          <tr>
                            <th>产品</th>
                            <th>风险</th>
                            <th>权重</th>
                            <th>配置金额</th>
                          </tr>
                        </thead>

                        <tbody>
                          {portfolio.allocation_items.map(
                            (item) => (
                              <tr
                                key={
                                  item.product_id
                                }
                              >
                                <td>
                                  <b>
                                    {
                                      item.product_name
                                    }
                                  </b>
                                </td>

                                <td>
                                  <span className="risk-tag">
                                    {
                                      item.risk_level
                                    }
                                  </span>
                                </td>

                                <td>
                                  {percent(
                                    item.weight,
                                    2
                                  )}
                                </td>

                                <td>
                                  {exactMoney(
                                    item.allocation_amount
                                  )}
                                </td>
                              </tr>
                            )
                          )}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <EmptyState
                status={portfolio.status}
                text={`${scenarioId}场景结果尚未准备完成。`}
              />
            )}
          </section>
        </div>
      </section>

      {/* ================= 营销运营闭环 ================= */}

      <section className="dashboard-section operation-section">
        <SectionTitle
          index="03"
          title="营销运营闭环"
          description="A2策略在工作台执行后，触达与响应事件实时回流到本页。"
        />

        <section className="card operation-loop">
          <div className="section-head">
            <div>
              <h2>策略执行闭环</h2>
              <p>
                策略生成 → 触达 → 响应，统一采用strategy_id事件口径
              </p>
            </div>

            <ResultStatus
              status={funnel.status}
            />
          </div>

          <div className="operation-steps">
            <div>
              <i>1</i>
              <strong>
                {strategyCount.toLocaleString()}
              </strong>
              <span>策略生成</span>
            </div>

            <b>→</b>

            <div>
              <i>2</i>
              <strong>
                {sentCount.toLocaleString()}
              </strong>
              <span>已触达</span>
            </div>

            <b>→</b>

            <div>
              <i>3</i>
              <strong>
                {respondedCount.toLocaleString()}
              </strong>
              <span>已响应</span>
            </div>
          </div>

          <div className="operation-kpis">
            <div>
              <span>
                <strong>策略触达率</strong>
                <small>
                  已触达策略 ÷ 全部策略
                </small>
              </span>

              <i>
                <b
                  style={{
                    width: `${
                      (touchRate ?? 0) *
                      100
                    }%`,
                  }}
                />
              </i>

              <em>{percent(touchRate)}</em>
            </div>

            <div>
              <span>
                <strong>
                  触达后响应率
                </strong>
                <small>
                  已响应策略 ÷ 已触达策略
                </small>
              </span>

              <i>
                <b
                  style={{
                    width: `${
                      (responseRate ?? 0) *
                      100
                    }%`,
                  }}
                />
              </i>

              <em>
                {responseRate == null
                  ? "尚未产生"
                  : percent(responseRate)}
              </em>
            </div>

            <div>
              <span>
                <strong>待执行策略</strong>
                <small>
                  尚未记录sent事件
                </small>
              </span>

              <i>
                <b
                  className="pending"
                  style={{
                    width: `${
                      strategyCount
                        ? (pendingCount /
                            strategyCount) *
                          100
                        : 0
                    }%`,
                  }}
                />
              </i>

              <em>
                {pendingCount.toLocaleString()} 条
              </em>
            </div>
          </div>

          <div className="operation-note">
            <span>
              客户口径：目标客户{" "}
              {funnel.target_customer_count.toLocaleString()}{" "}
              位 · 已触达{" "}
              {funnel.contacted_customer_count.toLocaleString()}{" "}
              位 · 已响应{" "}
              {funnel.responded_customer_count.toLocaleString()}{" "}
              位
            </span>

            <b>
              在营销运营工作台记录事件后，返回本页刷新即可查看变化。
            </b>
          </div>
        </section>
      </section>
    </>
  );
}