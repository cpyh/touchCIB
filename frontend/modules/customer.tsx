"use client";

import { useEffect, useMemo, useState } from "react";

import { api } from "../shared/api";
import { Metric, PageHead, Status, Table, riskNames } from "../shared/ui";

interface RosterRow {
  contact_id: string;
  customer_id: string;
  product_id: string;
  product_name: string;
  risk_level: string;
  channel: string;
  contact_date: string;
  response_prob: number;
}

interface Profile {
  customer_id: string;
  snapshot_date: string;
  age_group: string;
  city: string;
  occupation: string;
  income_level: string;
  register_date: string;
  aum: number;
  risk_appetite: string;
  vip_level: string;
  has_app: number;
  holding_product_count: number;
  holding_amount: number;
  login_count: number;
  consult_count: number;
  complaint_count: number;
  campaign_count: number;
  response_count: number;
  response_rate: number;
  last_contact_date: string | null;
}

interface CustomerPageProps {
  initialCustomerId?: string;
  onOpenMarketing: (customerId: string) => void;
  notify: (message: string) => void;
}

export function CustomerPage({
  initialCustomerId,
  onOpenMarketing,
  notify,
}: CustomerPageProps) {
  const [roster, setRoster] = useState<RosterRow[]>([]);
  const [rosterTotal, setRosterTotal] = useState(0);
  const [query, setQuery] = useState(initialCustomerId ?? "");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<{ total: number; customers: RosterRow[] }>(
      "/marketing/roster?size=100&sort=prob_desc",
    )
      .then((data) => {
        setRoster(data.customers);
        setRosterTotal(data.total);
      })
      .catch((error) => notify(`客户机会名单加载失败：${error.message}`));
  }, []);

  useEffect(() => {
    if (initialCustomerId) {
      setQuery(initialCustomerId);
      void loadProfile(initialCustomerId);
    }
  }, [initialCustomerId]);

  async function loadProfile(customerId: string) {
    const normalized = customerId.trim().toUpperCase();
    if (!normalized) {
      notify("请输入客户编号");
      return;
    }
    setBusy(true);
    try {
      const data = await api<Profile>(
        `/customers/${encodeURIComponent(normalized)}/profile`,
      );
      setProfile(data);
      setQuery(normalized);
    } catch (error) {
      notify(`客户画像加载失败：${(error as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const filteredRoster = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return roster;
    return roster.filter((row) =>
      [row.customer_id, row.product_id, row.product_name].some((value) =>
        value.toLowerCase().includes(keyword),
      ),
    );
  }, [query, roster]);

  return (
    <>
      <PageHead
        title="客户360与风险画像"
        description="以2026-03-31为统一数据截点，汇总客户属性、持仓、行为和历史触达，支撑后续营销策略解释。"
        action={<Status>DWS实体画像表</Status>}
      />

      <section className="card block competition-strip">
        <div className="metrics">
          <Metric label="分析基准日" value="2026-03-31" note="统一快照口径" gold />
          <Metric label="客户粒度" value="8,000" note="customer_id唯一" />
          <Metric label="数据层级" value="DWS" note="ODS→DWD→DWS" />
          <Metric label="时间防护" value="as-of" note="不使用未来行为与持仓" />
        </div>
      </section>

      {!profile && (
        <section className="card block customer-records">
          <div className="section-head">
            <div>
              <h2>客户机会入口</h2>
              <p>A1响应概率最高的前100条触达记录；也可以直接输入任意客户编号查询DWS画像。</p>
            </div>
            <Status>{rosterTotal.toLocaleString()}条预测记录</Status>
          </div>
          <div className="customer-toolbar customer-query-bar">
            <label className="customer-search">
              <span>⌕</span>
              <input
                aria-label="客户编号或产品"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void loadProfile(query);
                }}
                placeholder="输入客户编号，例如 C000010"
              />
              {query && <button onClick={() => setQuery("")}>×</button>}
            </label>
            <button className="primary" disabled={busy} onClick={() => void loadProfile(query)}>
              {busy ? "查询中…" : "查询客户画像"}
            </button>
          </div>
          <div className="customer-result-meta">
            <span>当前匹配 <b>{filteredRoster.length}</b> 条高意向机会</span>
            <small>A1 response_prob</small>
          </div>
          <div className="table customer-table">
            <table>
              <thead>
                <tr>
                  {[
                    "客户编号",
                    "关联产品",
                    "风险等级",
                    "触达日期",
                    "响应概率",
                    "",
                  ].map((header) => <th key={header}>{header}</th>)}
                </tr>
              </thead>
              <tbody>
                {filteredRoster.map((row) => (
                  <tr key={row.contact_id} onClick={() => void loadProfile(row.customer_id)}>
                    <td><b>{row.customer_id}</b></td>
                    <td>{row.product_name}<small>{row.product_id}</small></td>
                    <td><span className={`risk-pill ${row.risk_level.toLowerCase()}`}>{row.risk_level}</span></td>
                    <td>{row.contact_date}</td>
                    <td><b>{(row.response_prob * 100).toFixed(1)}%</b></td>
                    <td><button className="row-action">查看画像 ›</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {profile && (
        <section className="card block customer-records">
          <div className="section-head">
            <div>
              <h2>客户档案详情</h2>
              <p>画像快照、业务事实和营销证据均可向下追溯。</p>
            </div>
            <button className="secondary" onClick={() => setProfile(null)}>← 返回机会名单</button>
          </div>

          <div className="profile-bar">
            <div className="avatar">{profile.customer_id.slice(-2)}</div>
            <div className="profile-info">
              <div>
                <h3>{profile.customer_id}</h3>
                <span>{profile.vip_level}</span>
                <Status warn={profile.complaint_count > 0}>
                  {profile.complaint_count > 0 ? "存在投诉记录" : "无投诉记录"}
                </Status>
              </div>
              <p>{profile.age_group} · {profile.city} · {profile.occupation} · 收入{profile.income_level}</p>
              <div className="tags">
                <i>快照 {profile.snapshot_date}</i>
                <i>{profile.has_app ? "App已安装" : "App未安装"}</i>
                <i>历史响应率 {(profile.response_rate * 100).toFixed(1)}%</i>
              </div>
            </div>
            <div className="aum">
              <small>资产管理规模</small>
              <strong>¥ {profile.aum.toLocaleString("zh-CN")}</strong>
              <span>持仓产品 {profile.holding_product_count} 款</span>
            </div>
            <div className="risk">
              <small>风险偏好</small>
              <strong>{profile.risk_appetite}</strong>
              <span>{riskNames[profile.risk_appetite]}</span>
            </div>
          </div>

          <div className="profile-grid">
            <div className="card inner">
              <div className="overview">
                <article>
                  <h4>静态属性</h4>
                  <dl>
                    <div><dt>年龄段</dt><dd>{profile.age_group}</dd></div>
                    <div><dt>城市</dt><dd>{profile.city}</dd></div>
                    <div><dt>职业</dt><dd>{profile.occupation}</dd></div>
                    <div><dt>注册日期</dt><dd>{profile.register_date}</dd></div>
                  </dl>
                </article>
                <article>
                  <h4>持仓事实</h4>
                  <Table
                    headers={["指标", "数值"]}
                    rows={[
                      ["持仓产品", `${profile.holding_product_count}款`],
                      ["持仓金额", `¥${profile.holding_amount.toLocaleString("zh-CN")}`],
                    ]}
                  />
                </article>
                <article>
                  <h4>行为事实</h4>
                  <div className="stats">
                    <div><b>{profile.login_count}</b><span>登录</span></div>
                    <div><b>{profile.consult_count}</b><span>咨询</span></div>
                    <div><b>{profile.complaint_count}</b><span>投诉</span></div>
                  </div>
                </article>
                <article>
                  <h4>营销事实</h4>
                  <div className="stats">
                    <div><b>{profile.campaign_count}</b><span>历史触达</span></div>
                    <div><b>{profile.response_count}</b><span>历史响应</span></div>
                    <div><b>{(profile.response_rate * 100).toFixed(0)}%</b><span>响应率</span></div>
                  </div>
                </article>
              </div>
            </div>

            <aside className="ai-card">
              <div className="ai-title">
                <b>证</b>
                <span><strong>推荐证据摘要</strong><small>来自结构化画像，不调用大模型</small></span>
              </div>
              <p>
                该客户风险偏好为{riskNames[profile.risk_appetite]}，资产规模约
                {Math.round(profile.aum / 10000)}万元；历史触达{profile.campaign_count}次，
                响应率{(profile.response_rate * 100).toFixed(1)}%。策略生成需同时满足风险、渠道和投诉规则。
              </p>
              <div className="evidence">
                <small>可追溯依据</small>
                <span>风险偏好：{profile.risk_appetite}</span>
                <span>渠道状态：{profile.has_app ? "App可触达" : "App不可触达"}</span>
                <span>画像快照：{profile.snapshot_date}</span>
              </div>
              <button onClick={() => onOpenMarketing(profile.customer_id)}>查看Top 3营销策略 →</button>
              <em>严格使用快照日及以前的数据</em>
            </aside>
          </div>
        </section>
      )}
    </>
  );
}
