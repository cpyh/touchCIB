"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  CustomerApiError,
  CustomerCreatePayload,
  CustomerListItem,
  CustomerProfile,
  createCustomer,
  getCustomerProfile,
  listCustomers,
} from "../shared/customer-api";
import { api } from "../shared/api";
import { channelNames } from "../shared/ui";
import { formatNumber, money, percent } from "../shared/format";

interface StrategyItem {
  strategy_id: string;
  rank: number;
  product_id: string;
  product_name: string;
  expected_return: number;
  recommended_channel: string;
  status: string;
  model_prob: number | null;
}

interface LinkageData {
  strategies: StrategyItem[] | null;
  strategyMessage: string;
}

const PAGE_SIZE = 20;
const cities = ["上海", "北京", "南京", "南通", "常州", "徐州", "无锡", "杭州", "深圳", "苏州"];
const riskLevels = ["R1", "R2", "R3", "R4", "R5"];
const vipLevels = ["普通", "银卡", "金卡", "钻石"];
const ageGroups = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"];
const occupations = ["专业技术", "个体经营", "企业职员", "公务员", "其他", "退休"];
const incomeLevels = ["10万以下", "10-30万", "30-50万", "50万以上"];

type CustomerTab = "overview" | "holding" | "behavior" | "risk";

interface FormState {
  age_group: string;
  city: string;
  occupation: string;
  income_level: string;
  register_date: string;
  aum: string;
  vip_level: string;
  has_app: boolean;
}

const initialForm = (businessDate: string): FormState => ({
  age_group: "35-44",
  city: "上海",
  occupation: "企业职员",
  income_level: "30-50万",
  register_date: businessDate,
  aum: "650000",
  vip_level: "金卡",
  has_app: true,
});

function StatusPill({ children, warn = false }: { children: React.ReactNode; warn?: boolean }) {
  return <span className={warn ? "status warn" : "status"}><i />{children}</span>;
}

function errorMessage(error: unknown) {
  return error instanceof CustomerApiError ? error.message : "请求失败，请稍后重试";
}

function activity(profile: CustomerProfile) {
  const total = Object.values(profile.behavior_profile.recent_30d_counts).reduce((sum, value) => sum + value, 0);
  if (total >= 5) return "高活跃";
  if (total > 0) return "中等活跃";
  return "低活跃";
}

function buildStructuredInsights(profile: CustomerProfile) {
  const { basic_info: basic, asset_profile: asset, behavior_profile: behavior } = profile;
  const assessment = profile.risk_assessment;
  const riskMismatch = Boolean(assessment && assessment.level !== basic.risk_appetite);
  const largestHolding = asset.holdings.reduce(
    (largest, holding) => Math.max(largest, holding.amount),
    0,
  );
  const largestRatio = asset.holding_amount > 0 ? largestHolding / asset.holding_amount : null;
  const recent = behavior.recent_30d_counts;

  const riskText = riskMismatch
    ? `规则 ${assessment?.level} ≠ 登记 ${basic.risk_appetite}，推荐前复核。`
    : assessment
      ? `规则与登记一致：${basic.risk_appetite} · ${basic.risk_label}。`
      : `登记 ${basic.risk_appetite} · ${basic.risk_label}，推荐前核验适当性。`;

  const assetText = asset.holding_product_count === 0
    ? "暂无持仓，可进入智能投顾构建组合。"
    : `${formatNumber(asset.holding_product_count)} 款 · 单品集中 ${percent(largestRatio)} · 高流动 ${percent(asset.high_liquidity_ratio)}`;

  const behaviorText = recent.complaint > 0
    ? `近30天投诉 ${formatNumber(recent.complaint)} 次，服务前优先回访。`
    : recent.consult > 0
      ? `近30天咨询 ${formatNumber(recent.consult)} 次 · 登录 ${formatNumber(recent.login)} 次，建议及时跟进。`
      : recent.login > 0
        ? `近30天登录 ${formatNumber(recent.login)} 次、暂无咨询，先确认需求。`
        : "近30天无登录咨询，建议先确认需求。";

  return [
    { label: "风险边界", text: riskText, warn: riskMismatch },
    { label: "资产结构", text: assetText, warn: false },
    { label: "服务信号", text: behaviorText, warn: recent.complaint > 0 },
  ];
}

function paginationItems(current: number, total: number): Array<number | "ellipsis"> {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);

  const items: Array<number | "ellipsis"> = [1];
  let start = Math.max(2, current - 1);
  let end = Math.min(total - 1, current + 1);
  if (current <= 4) end = 5;
  if (current >= total - 3) start = total - 4;
  if (start > 2) items.push("ellipsis");
  for (let pageNumber = start; pageNumber <= end; pageNumber += 1) items.push(pageNumber);
  if (end < total - 1) items.push("ellipsis");
  items.push(total);
  return items;
}

interface CustomerPageProps {
  businessDate: string;
  historical: boolean;
  initialCustomerId: string;
  onOpenMarketing: (customerId: string) => void;
  onOpenPortfolio: (customerId: string) => void;
  notify?: (message: string) => void;
}

export function CustomerPage(props: CustomerPageProps) {
  const [items, setItems] = useState<CustomerListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [queryInput, setQueryInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [riskFilter, setRiskFilter] = useState("");
  const [vipFilter, setVipFilter] = useState("");
  const [cityFilter, setCityFilter] = useState("");
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [profile, setProfile] = useState<CustomerProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [profileRefreshKey, setProfileRefreshKey] = useState(0);
  const [customerTab, setCustomerTab] = useState<CustomerTab>("overview");

  const [linkage, setLinkage] = useState<LinkageData | null>(null);
  const [linkageLoading, setLinkageLoading] = useState(false);

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<FormState>(() => initialForm(props.businessDate));
  const [createBusy, setCreateBusy] = useState(false);
  const [createError, setCreateError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    const externalId = props.initialCustomerId?.trim().toUpperCase();
    if (externalId && externalId !== selectedId) openCustomer(externalId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props.initialCustomerId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const nextKeyword = queryInput.trim();
      if (nextKeyword !== keyword) {
        setListLoading(true);
        setListError("");
        setKeyword(nextKeyword);
        setPage(1);
      }
    }, 350);
    return () => window.clearTimeout(timer);
  }, [queryInput, keyword]);

  useEffect(() => {
    const controller = new AbortController();
    listCustomers(
      {
        page,
        pageSize: PAGE_SIZE,
        keyword: keyword || undefined,
        riskAppetite: riskFilter || undefined,
        vipLevel: vipFilter || undefined,
        city: cityFilter || undefined,
        businessDate: props.businessDate,
      },
      controller.signal,
    )
      .then(data => {
        setItems(data.items);
        setTotal(data.total);
      })
      .catch(error => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setListError(errorMessage(error));
        setItems([]);
      })
      .finally(() => {
        if (!controller.signal.aborted) setListLoading(false);
      });
    return () => controller.abort();
  }, [page, keyword, riskFilter, vipFilter, cityFilter, refreshKey, props.businessDate]);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    getCustomerProfile(selectedId, props.businessDate, controller.signal)
      .then(setProfile)
      .catch(error => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setProfileError(errorMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setProfileLoading(false);
      });
    return () => controller.abort();
  }, [selectedId, profileRefreshKey, props.businessDate]);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    setLinkage(null);
    setLinkageLoading(true);
    api<{ items: StrategyItem[] }>(
      `/customers/${selectedId}/strategies?business_date=${encodeURIComponent(props.businessDate)}`,
      { signal: controller.signal },
    )
      .then(data => {
        setLinkage({ strategies: data.items, strategyMessage: "" });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setLinkage({
          strategies: null,
          strategyMessage: error instanceof Error ? error.message : "策略加载失败，请稍后重试",
        });
      })
      .finally(() => {
        if (!controller.signal.aborted) setLinkageLoading(false);
      });
    return () => controller.abort();
  }, [selectedId, props.businessDate]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const visiblePages = paginationItems(page, totalPages);
  const currentActivity = profile ? activity(profile) : "";
  const basic = profile?.basic_info;
  const asset = profile?.asset_profile;
  const behavior = profile?.behavior_profile;
  const activeFilterCount = [keyword, riskFilter, vipFilter, cityFilter].filter(Boolean).length;
  const bestOpportunity = linkage?.strategies?.length
    ? [...linkage.strategies].sort((left, right) => (right.model_prob ?? 0) - (left.model_prob ?? 0))[0]
    : null;
  const primaryStrategy = linkage?.strategies?.find(item => item.rank === 1)
    ?? linkage?.strategies?.[0]
    ?? null;
  const structuredInsights = profile ? buildStructuredInsights(profile) : [];

  function resetFilters() {
    setListLoading(true);
    setListError("");
    setQueryInput("");
    setKeyword("");
    setRiskFilter("");
    setVipFilter("");
    setCityFilter("");
    setPage(1);
  }

  function openCustomer(customerId: string) {
    setProfile(null);
    setLinkage(null);
    setLinkageLoading(true);
    setProfileLoading(true);
    setProfileError("");
    setSelectedId(customerId);
    setCustomerTab("overview");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function closeCustomer() {
    setSelectedId(null);
    setProfile(null);
    setLinkage(null);
    setLinkageLoading(false);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function goToPage(nextPage: number) {
    if (nextPage === page || nextPage < 1 || nextPage > totalPages || listLoading) return;
    setListLoading(true);
    setPage(nextPage);
  }

  async function submitCustomer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateBusy(true);
    setCreateError("");
    const payload: CustomerCreatePayload = {
      ...createForm,
      aum: Number(createForm.aum),
    };
    try {
      const created = await createCustomer(payload);
      setCreateOpen(false);
      setCreateForm(initialForm(props.businessDate));
      setNotice(`客户 ${created.customer_id} 已创建，风险评估结果为 ${created.risk_appetite} ${created.risk_label}`);
      setListLoading(true);
      setRefreshKey(value => value + 1);
      openCustomer(created.customer_id);
    } catch (error) {
      setCreateError(errorMessage(error));
    } finally {
      setCreateBusy(false);
    }
  }

  return <>
    <div className="page-head customer-page-head">
      <div><small>客户经理服务台</small><h1>客户进件与风险评估</h1><p>从客户识别、风险核验到投顾与营销行动，在一个服务流程中完成。</p></div>
      <button className="primary import-button" disabled={props.historical} title={props.historical ? "历史快照只读，请切回当前运营日" : undefined} onClick={() => { setCreateError(""); setCreateOpen(true); }}>＋ 新客户进件</button>
    </div>

    {notice && <div className="notice"><b>✓</b><span>{notice}</span><button onClick={() => setNotice("")}>关闭</button></div>}

    <section className="card block customer-records">
      <div className="section-head customer-directory-head">
        <div><small className="customer-section-kicker">{selectedId ? "正在服务" : "存量客户服务"}</small><h2>{selectedId ? `客户 ${selectedId}` : "选择下一位服务客户"}</h2><p>{selectedId ? "先确认客户现状与风险依据，再直接发起下一步业务动作。" : "按客户特征筛选，结合资产、风险和可触达状态决定服务顺序。"}</p></div>
        <div className="customer-head-actions">
          {selectedId
            ? <StatusPill>实时画像</StatusPill>
            : listError
              ? <StatusPill warn>客户服务异常</StatusPill>
              : <StatusPill>{listLoading ? "正在同步客户" : `${formatNumber(total)} 位客户`}</StatusPill>}
          {selectedId && <button className="secondary" onClick={closeCustomer}>← 返回客户名录</button>}
        </div>
      </div>

      <div className="customer-service-flow" aria-label="客户服务流程">
        <span className="on"><i>1</i><b>定位客户</b><small>搜索或筛选</small></span>
        <em>→</em>
        <span className={selectedId ? "on" : ""}><i>2</i><b>核验画像</b><small>风险与需求证据</small></span>
        <em>→</em>
        <span className={selectedId ? "on" : ""}><i>3</i><b>发起服务</b><small>营销或投顾</small></span>
      </div>

      {!selectedId && <>
        <div className="customer-toolbar api-toolbar">
          <label className="customer-search"><span>⌕</span><input aria-label="模糊搜索客户" value={queryInput} onChange={event => setQueryInput(event.target.value)} placeholder="搜索客户编号、城市或职业" />{queryInput && <button aria-label="清空搜索" onClick={() => setQueryInput("")}>×</button>}</label>
          <select aria-label="按风险等级筛选" value={riskFilter} onChange={event => { setListLoading(true); setListError(""); setRiskFilter(event.target.value); setPage(1); }}><option value="">全部风险</option>{riskLevels.map(option => <option key={option}>{option}</option>)}</select>
          <select aria-label="按客户等级筛选" value={vipFilter} onChange={event => { setListLoading(true); setListError(""); setVipFilter(event.target.value); setPage(1); }}><option value="">全部等级</option>{vipLevels.map(option => <option key={option}>{option}</option>)}</select>
          <select aria-label="按城市筛选" value={cityFilter} onChange={event => { setListLoading(true); setListError(""); setCityFilter(event.target.value); setPage(1); }}><option value="">全部城市</option>{cities.map(option => <option key={option}>{option}</option>)}</select>
          <button className="reset-filter" onClick={resetFilters}>重置条件</button>
        </div>
        <div className="customer-result-meta"><span>{listError ? "客户名录加载失败" : <>共 <b>{formatNumber(total)}</b> 位客户，当前第 <b>{formatNumber(page)}</b> 页</>}</span><small>{activeFilterCount ? `已应用 ${formatNumber(activeFilterCount)} 个筛选条件` : "全量客户"}</small></div>
        {listError && <div className="api-error"><b>无法读取客户数据</b><p>{listError}</p><button className="secondary" onClick={() => { setListLoading(true); setListError(""); setRefreshKey(value => value + 1); }}>重新连接</button></div>}
        {!listError && <div className={`table customer-table ${listLoading ? "is-loading" : ""}`}>
          <table><thead><tr>{["客户", "客户特征", "资产与等级", "风险偏好", "联系条件", "下一步"].map(header => <th key={header}>{header}</th>)}</tr></thead><tbody>{items.map(customer => <tr key={customer.customer_id}><td><div className="customer-id"><i>{customer.customer_id.slice(-2)}</i><span><b>{customer.customer_id}</b><small>{customer.city}</small></span></div></td><td><b>{customer.age_group} · {customer.occupation}</b><small>关系始于 {customer.register_date}</small></td><td><b className="customer-aum-inline">{money(customer.aum)}</b><small><span className="vip-tag">{customer.vip_level}客户</span></small></td><td><span className={`risk-pill ${customer.risk_appetite.toLowerCase()}`}>{customer.risk_appetite}</span><small>{customer.risk_label}</small></td><td><span className={customer.has_app ? "app-state on" : "app-state"}>{customer.has_app ? "App 可触达" : "需线下联系"}</span><small>{customer.has_app ? "支持 App 推送" : "不适用 App 推送"}</small></td><td><button className="row-action" onClick={() => openCustomer(customer.customer_id)} aria-label={`查看${customer.customer_id}客户详情`}>进入服务 →</button></td></tr>)}</tbody></table>
          {listLoading && <div className="table-loading">正在从客户画像服务读取数据…</div>}
          {!listLoading && items.length === 0 && <div className="empty-result"><b>未找到匹配客户</b><span>请缩短关键词或重置筛选条件。</span></div>}
        </div>}
        {!listError && <div className="customer-pagination"><span>每页 {formatNumber(PAGE_SIZE)} 条 · 共 {formatNumber(totalPages)} 页</span><nav aria-label="客户列表分页"><button aria-label="上一页" disabled={page <= 1 || listLoading} onClick={() => goToPage(page - 1)}>‹</button>{visiblePages.map((item, index) => item === "ellipsis" ? <i className="pagination-ellipsis" key={`ellipsis-${index}`}>…</i> : <button key={item} className={page === item ? "on" : ""} aria-current={page === item ? "page" : undefined} disabled={listLoading} onClick={() => goToPage(item)}>{formatNumber(item)}</button>)}<button aria-label="下一页" disabled={page >= totalPages || listLoading} onClick={() => goToPage(page + 1)}>›</button></nav></div>}
      </>}

      {selectedId && <>
        {profileLoading && <div className="profile-state"><span className="spinner" /><b>正在生成客户全景画像…</b></div>}
        {profileError && <div className="api-error"><b>客户画像加载失败</b><p>{profileError}</p><button className="secondary" onClick={() => { setProfileLoading(true); setProfileError(""); setProfileRefreshKey(value => value + 1); }}>重新加载</button></div>}
        {profile && basic && asset && behavior && !profileLoading && <>
          <div className="service-profile-bar">
            <div className="service-identity"><div className="avatar">{basic.customer_id.slice(-2)}</div><span><small>{basic.vip_level}客户 · {currentActivity}</small><h3>{basic.customer_id}</h3><p>{basic.age_group} · {basic.city} · {basic.occupation} · 收入{basic.income_level}</p></span></div>
            <div className="service-profile-metrics"><span><small>资产管理规模</small><strong>{money(basic.aum)}</strong><em>持仓 {money(asset.holding_amount)}</em></span><span><small>风险偏好</small><strong>{basic.risk_appetite} · {basic.risk_label}</strong><em>截至 {profile.as_of_date}</em></span><span><small>联系条件</small><strong>{basic.has_app ? "App 可触达" : "需线下联系"}</strong><em>{currentActivity} · 历史触达 {formatNumber(profile.campaign_summary?.contact_count ?? 0)} 次</em></span></div>
            <div className="service-profile-tags">{behavior.tags.length ? behavior.tags.map(tag => <i key={tag}>{tag}</i>) : <i>暂无动态标签</i>}</div>
          </div>

          <div className="customer-service-layout">
            <div className="card inner service-evidence-panel">
              <div className="tabs">{[["overview", "画像概览"], ["risk", "风险评估"], ["holding", "资产持仓"], ["behavior", "行为概览"]].map(tab => <button key={tab[0]} className={customerTab === tab[0] ? "on" : ""} onClick={() => setCustomerTab(tab[0] as CustomerTab)}>{tab[1]}</button>)}</div>
              {customerTab === "overview" && <div className="overview api-overview">
                <article><h4>客户关系</h4><dl><div><dt>年龄段</dt><dd>{basic.age_group}</dd></div><div><dt>所在城市</dt><dd>{basic.city}</dd></div><div><dt>职业</dt><dd>{basic.occupation}</dd></div><div><dt>关系建立</dt><dd>{basic.register_date}</dd></div></dl></article>
                <article><h4>适当性判断</h4><div className="risk-row"><b>{basic.risk_appetite}</b><span>{basic.risk_label}<small>当前登记风险等级</small></span></div><div className="risk-scale dynamic">{riskLevels.map(level => <i key={level} className={Number(level.slice(1)) <= Number(basic.risk_appetite.slice(1)) ? "active" : ""} />)}</div><p>进入产品推荐前，先核验风险等级与产品准入。</p></article>
                <article><h4>资产现状</h4><dl><div><dt>持仓产品</dt><dd>{formatNumber(asset.holding_product_count)} 款</dd></div><div><dt>持仓覆盖率</dt><dd>{basic.aum > 0 ? percent(asset.holding_amount / basic.aum) : "—"}</dd></div><div><dt>高流动性比例</dt><dd>{percent(asset.high_liquidity_ratio)}</dd></div><div><dt>加权预期收益</dt><dd>{percent(asset.weighted_expected_return)}</dd></div></dl></article>
                <article><h4>互动与触达</h4><div className="stats"><div><b>{formatNumber(behavior.recent_30d_counts.login)}</b><span>近30天登录</span></div><div><b>{formatNumber(behavior.recent_30d_counts.consult)}</b><span>近30天咨询</span></div><div><b>{percent(profile.campaign_summary?.response_rate)}</b><span>历史响应率</span></div></div><p>最近触达：{profile.campaign_summary?.last_contact_date ?? "暂无"}</p></article>
              </div>}
              {customerTab === "holding" && <div className="table"><table><thead><tr>{["产品", "类型", "风险", "持仓金额", "流动性", "预期收益", "购买日期"].map(header => <th key={header}>{header}</th>)}</tr></thead><tbody>{asset.holdings.map(holding => <tr key={holding.holding_id}><td><b>{holding.product_id}</b><small>{holding.product_name}</small></td><td>{holding.product_type}</td><td><span className="risk-tag">{holding.risk_level}</span></td><td>{money(holding.amount)}</td><td>{holding.liquidity}</td><td>{percent(holding.expected_return)}</td><td>{holding.buy_date}</td></tr>)}</tbody></table>{asset.holdings.length === 0 && <div className="empty-result"><b>暂无持仓记录</b><span>该客户当前没有可识别的产品持仓。</span></div>}</div>}
              {customerTab === "risk" && profile?.risk_assessment && (() => { const ra = profile.risk_assessment; return <div className="risk-assessment"><div className="risk-score-card"><small>规则评估得分</small><strong>{formatNumber(ra.score)}</strong><span>映射等级 <b>{ra.level} · {ra.label}</b></span><div className="risk-band">{["R1","R2","R3","R4","R5"].map((level) => <i key={level} className={level === ra.level ? "on" : ""}><em>{level}</em></i>)}</div><p>基础分 {ra.base_score} + 四项因子分；评估口径与进件规则一致。</p>{ra.level !== profile.basic_info.risk_appetite && <p className="risk-mismatch">行内登记 {profile.basic_info.risk_appetite} · {profile.basic_info.risk_label}（存量客户以登记为准）</p>}</div><div className="risk-factors"><b>评估因子明细</b><ul><li><span>基础分</span><em>{ra.base_score > 0 ? "+" : ""}{formatNumber(ra.base_score)}</em></li>{ra.factors.map((factor) => <li key={factor.factor}><span>{factor.factor} · {factor.value}</span><em>{factor.score > 0 ? "+" : ""}{formatNumber(factor.score)}</em></li>)}<li className="total"><span>总分</span><em>{formatNumber(ra.score)}</em></li></ul></div></div>; })()}
              {customerTab === "behavior" && <div className="behavior-panel"><div className="behavior-metrics">{[["登录", behavior.total_counts.login, behavior.recent_30d_counts.login], ["咨询", behavior.total_counts.consult, behavior.recent_30d_counts.consult], ["投诉", behavior.total_counts.complaint, behavior.recent_30d_counts.complaint]].map(item => <article key={item[0]}><small>{item[0]}</small><strong>{formatNumber(Number(item[1]))}</strong><span>近 30 天 {formatNumber(Number(item[2]))} 次</span></article>)}</div><div className="latest-event"><b>最近一次行为</b><span>{behavior.latest_event_type ? `${behavior.latest_event_type} · ${behavior.latest_event_date}` : "暂无行为记录"}</span></div><div className="tags">{behavior.tags.map(tag => <i key={tag}>{tag}</i>)}</div></div>}
            </div>
            <aside className="manager-next-step">
              <header><small>客户经理下一步</small><h3>{linkageLoading ? "正在读取客户策略" : primaryStrategy ? `优先跟进 ${primaryStrategy.product_name}` : "先完成需求确认"}</h3><p>{linkageLoading ? "结构化画像已就绪，营销策略正在加载。" : primaryStrategy ? `${channelNames[primaryStrategy.recommended_channel] ?? primaryStrategy.recommended_channel}触达 · ${primaryStrategy.status}` : (linkage?.strategyMessage || "当前暂无可执行策略，建议先核实客户资金安排。")}</p></header>
              <div className="service-signal-grid"><span><small>最高响应概率</small><strong>{bestOpportunity?.model_prob != null ? percent(bestOpportunity.model_prob) : "—"}</strong></span><span><small>历史响应率</small><strong>{percent(profile.campaign_summary?.response_rate)}</strong></span><span><small>持仓覆盖率</small><strong>{basic.aum > 0 ? percent(asset.holding_amount / basic.aum) : "—"}</strong></span></div>
              {primaryStrategy && <div className="primary-strategy"><small>TOP1 策略</small><b>{primaryStrategy.product_id} · {primaryStrategy.product_name}</b><span>预期收益 {percent(primaryStrategy.expected_return)} · {channelNames[primaryStrategy.recommended_channel] ?? primaryStrategy.recommended_channel}</span></div>}
              <div className="manager-actions"><button className="primary" onClick={() => props.onOpenMarketing(basic.customer_id)}>打开 Top3 营销策略 →</button><button className="secondary" onClick={() => props.onOpenPortfolio(basic.customer_id)}>生成投顾配置方案 →</button></div>
              <section className="structured-insight">
                <div className="structured-insight-head"><span><i>规</i><b>结构化洞察</b></span><em>风险 · 持仓 · 行为</em></div>
                <ul>{structuredInsights.map(insight => <li className={insight.warn ? "warn" : ""} key={insight.label}><b>{insight.label}</b><span>{insight.text}</span></li>)}</ul>
              </section>
            </aside>
          </div>
        </>}
      </>}
    </section>

    {createOpen && <div className="modal-backdrop" role="button" tabIndex={0} aria-label="关闭新建客户对话框" onKeyDown={event => { if (event.key === "Escape" && !createBusy) setCreateOpen(false); }} onMouseDown={event => { if (event.target === event.currentTarget && !createBusy) setCreateOpen(false); }}><section className="customer-modal" role="dialog" aria-modal="true" aria-labelledby="create-customer-title"><button className="close" aria-label="关闭" onClick={() => setCreateOpen(false)}>×</button><header><small>NEW CUSTOMER</small><h2 id="create-customer-title">新建客户并自动评估风险</h2><p>客户编号由后端生成，风险等级由规则服务计算。</p></header><form onSubmit={submitCustomer}><div className="form-grid"><label>年龄段<select value={createForm.age_group} onChange={event => setCreateForm({ ...createForm, age_group: event.target.value })}>{ageGroups.map(value => <option key={value}>{value}</option>)}</select></label><label>城市<input required maxLength={50} value={createForm.city} onChange={event => setCreateForm({ ...createForm, city: event.target.value })} /></label><label>职业<select value={createForm.occupation} onChange={event => setCreateForm({ ...createForm, occupation: event.target.value })}>{occupations.map(value => <option key={value}>{value}</option>)}</select></label><label>收入区间<select value={createForm.income_level} onChange={event => setCreateForm({ ...createForm, income_level: event.target.value })}>{incomeLevels.map(value => <option key={value}>{value}</option>)}</select></label><label>注册日期<input required type="date" max={props.businessDate} value={createForm.register_date} onChange={event => setCreateForm({ ...createForm, register_date: event.target.value })} /></label><label>资产管理规模（元）<input required type="number" min="0" step="0.01" value={createForm.aum} onChange={event => setCreateForm({ ...createForm, aum: event.target.value })} /></label><label>客户等级<select value={createForm.vip_level} onChange={event => setCreateForm({ ...createForm, vip_level: event.target.value })}>{vipLevels.map(value => <option key={value}>{value}</option>)}</select></label><label className="switch-label">App状态<span><input type="checkbox" checked={createForm.has_app} onChange={event => setCreateForm({ ...createForm, has_app: event.target.checked })} /> 已安装 App</span></label></div>{createError && <div className="form-error">{createError}</div>}<footer><button type="button" className="secondary" disabled={createBusy} onClick={() => setCreateOpen(false)}>取消</button><button type="submit" className="primary" disabled={createBusy}>{createBusy ? "正在创建并评估…" : "创建客户并评估风险"}</button></footer></form></section></div>}
  </>;
}
