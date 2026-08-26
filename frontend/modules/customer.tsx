"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AiAnalysis,
  CUSTOMER_API_BASE_URL,
  CustomerApiError,
  CustomerCreatePayload,
  CustomerListItem,
  CustomerProfile,
  createCustomer,
  generateAiSummary,
  getCustomerProfile,
  listCustomers,
} from "../shared/customer-api";;

const PAGE_SIZE = 20;
const cities = ["上海", "北京", "南京", "南通", "常州", "徐州", "无锡", "杭州", "深圳", "苏州"];
const riskLevels = ["R1", "R2", "R3", "R4", "R5"];
const vipLevels = ["普通", "银卡", "金卡", "钻石"];
const ageGroups = ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"];
const occupations = ["专业技术", "个体经营", "企业职员", "公务员", "其他", "退休"];
const incomeLevels = ["10万以下", "10-30万", "30-50万", "50万以上"];

const dataSources = [
  ["客", "客户数据", "8,000"],
  ["产", "产品数据", "30"],
  ["持", "持仓数据", "8,579"],
  ["行", "行为数据", "13,142"],
  ["营", "营销数据", "50,000"],
] as const;

type CustomerTab = "overview" | "holding" | "behavior";

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

const initialForm = (): FormState => ({
  age_group: "35-44",
  city: "上海",
  occupation: "企业职员",
  income_level: "30-50万",
  register_date: new Date().toISOString().slice(0, 10),
  aum: "650000",
  vip_level: "金卡",
  has_app: true,
});

function StatusPill({ children, warn = false }: { children: React.ReactNode; warn?: boolean }) {
  return <span className={warn ? "status warn" : "status"}><i />{children}</span>;
}

function money(value: number) {
  return `¥ ${value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function percent(value: number | null) {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function errorMessage(error: unknown) {
  return error instanceof CustomerApiError ? error.message : "请求失败，请稍后重试";
}

function HighlightedText({ text, highlights }: { text: string; highlights: string[] }) {
  const terms = Array.from(new Set(highlights))
    .filter(term => term && text.includes(term))
    .sort((left, right) => right.length - left.length);
  if (!terms.length) return <>{text}</>;

  const escaped = terms.map(term => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const parts = text.split(new RegExp(`(${escaped.join("|")})`, "g"));
  const termSet = new Set(terms);
  return <>{parts.map((part, index) => termSet.has(part)
    ? <strong className="ai-highlight" key={`${part}-${index}`}>{part}</strong>
    : <span key={`${part}-${index}`}>{part}</span>)}</>;
}

function AiAnalysisPanel({ analysis }: { analysis: AiAnalysis }) {
  const sections = [
    ["画像概述", analysis.overview],
    ["需求洞察", analysis.insight],
    ["服务建议", analysis.suggestion],
  ] as const;
  return <div className="ai-analysis">{sections.map(([title, text]) => <section key={title}>
    <b>{title}</b>
    <p><HighlightedText text={text} highlights={analysis.highlights} /></p>
  </section>)}</div>;
}

function activity(profile: CustomerProfile) {
  const total = Object.values(profile.behavior_profile.recent_30d_counts).reduce((sum, value) => sum + value, 0);
  if (total >= 5) return "高活跃";
  if (total > 0) return "中等活跃";
  return "低活跃";
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
  initialCustomerId: string;
  onOpenMarketing: (customerId: string) => void;
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

  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState("");
  const [summaryProvider, setSummaryProvider] = useState<string | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<FormState>(initialForm);
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
  }, [page, keyword, riskFilter, vipFilter, cityFilter, refreshKey]);

  useEffect(() => {
    if (!selectedId) return;
    const controller = new AbortController();
    getCustomerProfile(selectedId, controller.signal)
      .then(setProfile)
      .catch(error => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setProfileError(errorMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setProfileLoading(false);
      });
    return () => controller.abort();
  }, [selectedId, profileRefreshKey]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const visiblePages = paginationItems(page, totalPages);
  const currentActivity = profile ? activity(profile) : "";
  const basic = profile?.basic_info;
  const asset = profile?.asset_profile;
  const behavior = profile?.behavior_profile;
  const sourceCounts = useMemo(
    () => dataSources.map((source, index) => index === 0 && total > 0 ? [source[0], source[1], total.toLocaleString("zh-CN")] : source),
    [total],
  );

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
    setProfileLoading(true);
    setProfileError("");
    setAiError("");
    setSelectedId(customerId);
    setCustomerTab("overview");
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
      setCreateForm(initialForm());
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

  async function refreshAiSummary() {
    if (!selectedId || !profile) return;
    setAiBusy(true);
    setAiError("");
    try {
      const result = await generateAiSummary(selectedId);
      setProfile({
        ...profile,
        ai_summary: result.analysis,
        ai_summary_generated_at: result.generated_at,
      });
      setSummaryProvider(`${result.provider} · ${result.model}`);
    } catch (error) {
      setAiError(errorMessage(error));
    } finally {
      setAiBusy(false);
    }
  }

  return <>
    <div className="page-head">
      <div><h1>客户画像与风险评估</h1><p>通过真实客户、持仓与行为数据，形成可追溯的客户全景视图。</p></div>
      <button className="primary import-button" onClick={() => { setCreateError(""); setCreateOpen(true); }}>＋ 新建客户</button>
    </div>

    {notice && <div className="notice"><b>✓</b><span>{notice}</span><button onClick={() => setNotice("")}>关闭</button></div>}

    <section className="card block">
      <div className="section-head"><div><h2>数据总览</h2><p>客户模块已切换为 Flask API 实时读取，其他数据源展示数据库导入规模。</p></div>{listError ? <StatusPill warn>接口连接失败</StatusPill> : <StatusPill>{listLoading ? "正在连接接口" : "实时接口已连接"}</StatusPill>}</div>
      <div className="source-grid">{sourceCounts.map((source, index) => <article className="source" key={source[1]}><b className={`s${index}`}>{source[0]}</b><span><strong>{source[1]}</strong><em>{source[2]} <small>条记录</small></em><StatusPill warn={index > 0}>{index === 0 ? "API实时读取" : "数据库已导入"}</StatusPill></span></article>)}</div>
    </section>

    <section className="card block customer-records">
      <div className="section-head"><div><h2>{selectedId ? "客户档案详情" : "客户档案"}</h2><p>{selectedId ? "画像内容来自客户详情接口，统计与风险结果均由后端生成。" : "支持客户编号、城市或职业模糊检索，并使用接口分页和组合筛选。"}</p></div>{selectedId && <button className="secondary" onClick={() => setSelectedId(null)}>← 返回客户列表</button>}</div>

      {!selectedId && <>
        <div className="customer-toolbar api-toolbar">
          <label className="customer-search"><span>⌕</span><input aria-label="模糊搜索客户" value={queryInput} onChange={event => setQueryInput(event.target.value)} placeholder="搜索客户编号、城市或职业" />{queryInput && <button aria-label="清空搜索" onClick={() => setQueryInput("")}>×</button>}</label>
          <select aria-label="按风险等级筛选" value={riskFilter} onChange={event => { setListLoading(true); setListError(""); setRiskFilter(event.target.value); setPage(1); }}><option value="">全部风险</option>{riskLevels.map(option => <option key={option}>{option}</option>)}</select>
          <select aria-label="按客户等级筛选" value={vipFilter} onChange={event => { setListLoading(true); setListError(""); setVipFilter(event.target.value); setPage(1); }}><option value="">全部等级</option>{vipLevels.map(option => <option key={option}>{option}</option>)}</select>
          <select aria-label="按城市筛选" value={cityFilter} onChange={event => { setListLoading(true); setListError(""); setCityFilter(event.target.value); setPage(1); }}><option value="">全部城市</option>{cities.map(option => <option key={option}>{option}</option>)}</select>
          <button className="reset-filter" onClick={resetFilters}>重置条件</button>
        </div>
        <div className="customer-result-meta"><span>{listError ? "客户列表加载失败" : <>共 <b>{total.toLocaleString("zh-CN")}</b> 位客户，当前第 <b>{page}</b> 页</>}</span><small>{CUSTOMER_API_BASE_URL}</small></div>
        {listError && <div className="api-error"><b>无法读取客户数据</b><p>{listError}</p><button className="secondary" onClick={() => { setListLoading(true); setListError(""); setRefreshKey(value => value + 1); }}>重新连接</button></div>}
        {!listError && <div className={`table customer-table ${listLoading ? "is-loading" : ""}`}>
          <table><thead><tr>{["客户编号", "客户等级", "年龄段 / 城市", "职业", "资产管理规模", "风险偏好", "App状态", "注册日期", ""].map(header => <th key={header}>{header}</th>)}</tr></thead><tbody>{items.map(customer => <tr key={customer.customer_id}><td><div className="customer-id"><i>{customer.customer_id.slice(-2)}</i><b>{customer.customer_id}</b></div></td><td><span className="vip-tag">{customer.vip_level}客户</span></td><td><b>{customer.age_group}</b><small>{customer.city}</small></td><td>{customer.occupation}</td><td className="money-cell">{money(customer.aum)}</td><td><span className={`risk-pill ${customer.risk_appetite.toLowerCase()}`}>{customer.risk_appetite}</span><small>{customer.risk_label}</small></td><td><span className={customer.has_app ? "app-state on" : "app-state"}>{customer.has_app ? "已安装" : "未安装"}</span></td><td>{customer.register_date}</td><td><button className="row-action" onClick={() => openCustomer(customer.customer_id)} aria-label={`查看${customer.customer_id}客户详情`}>查看 ›</button></td></tr>)}</tbody></table>
          {listLoading && <div className="table-loading">正在从客户画像服务读取数据…</div>}
          {!listLoading && items.length === 0 && <div className="empty-result"><b>未找到匹配客户</b><span>请缩短关键词或重置筛选条件。</span></div>}
        </div>}
        {!listError && <div className="customer-pagination"><span>每页 {PAGE_SIZE} 条 · 共 {totalPages} 页</span><nav aria-label="客户列表分页"><button aria-label="上一页" disabled={page <= 1 || listLoading} onClick={() => goToPage(page - 1)}>‹</button>{visiblePages.map((item, index) => item === "ellipsis" ? <i className="pagination-ellipsis" key={`ellipsis-${index}`}>…</i> : <button key={item} className={page === item ? "on" : ""} aria-current={page === item ? "page" : undefined} disabled={listLoading} onClick={() => goToPage(item)}>{item}</button>)}<button aria-label="下一页" disabled={page >= totalPages || listLoading} onClick={() => goToPage(page + 1)}>›</button></nav></div>}
      </>}

      {selectedId && <>
        {profileLoading && <div className="profile-state"><span className="spinner" /><b>正在生成客户全景画像…</b></div>}
        {profileError && <div className="api-error"><b>客户画像加载失败</b><p>{profileError}</p><button className="secondary" onClick={() => { setProfileLoading(true); setProfileError(""); setProfileRefreshKey(value => value + 1); }}>重新加载</button></div>}
        {profile && basic && asset && behavior && !profileLoading && <>
          <div className="profile-bar"><div className="avatar">{basic.customer_id.slice(-2)}</div><div className="profile-info"><div><h3>{basic.customer_id}</h3><span>{basic.vip_level}客户</span><StatusPill warn={currentActivity === "低活跃"}>{currentActivity}</StatusPill></div><p>{basic.age_group} · {basic.city} · {basic.occupation} · 收入{basic.income_level}</p><div className="tags">{behavior.tags.length ? behavior.tags.map(tag => <i key={tag}>{tag}</i>) : <i>暂无动态标签</i>}<i>{basic.has_app ? "App已安装" : "App未安装"}</i></div></div><div className="aum"><small>资产管理规模</small><strong>{money(basic.aum)}</strong><span>可识别持仓 {money(asset.holding_amount)}</span></div><div className="risk"><small>风险偏好</small><strong>{basic.risk_appetite}</strong><span>{basic.risk_label}</span></div>
          <div className="profile-to-marketing"><button className="primary" onClick={() => props.onOpenMarketing(basic.customer_id)}>查看Top3营销策略 →</button></div></div>
          <div className="profile-grid">
            <div className="card inner">
              <div className="tabs">{[["overview", "画像概览"], ["holding", "资产持仓"], ["behavior", "行为概览"]].map(tab => <button key={tab[0]} className={customerTab === tab[0] ? "on" : ""} onClick={() => setCustomerTab(tab[0] as CustomerTab)}>{tab[1]}</button>)}</div>
              {customerTab === "overview" && <div className="overview api-overview">
                <article><h4>基础信息</h4><dl><div><dt>年龄段</dt><dd>{basic.age_group}</dd></div><div><dt>城市</dt><dd>{basic.city}</dd></div><div><dt>职业</dt><dd>{basic.occupation}</dd></div><div><dt>注册日期</dt><dd>{basic.register_date}</dd></div></dl></article>
                <article><h4>风险信息</h4><div className="risk-row"><b>{basic.risk_appetite}</b><span>{basic.risk_label}<small>数据库风险评估结果</small></span></div><div className="risk-scale dynamic">{riskLevels.map(level => <i key={level} className={Number(level.slice(1)) <= Number(basic.risk_appetite.slice(1)) ? "active" : ""} />)}</div><p>统计截止日期：{profile.as_of_date}</p></article>
                <article><h4>资产结构</h4>{asset.product_type_distribution.length ? <div className="mini-bars">{asset.product_type_distribution.map(item => <label key={item.name}>{item.name}<i><b style={{ width: `${(item.ratio ?? 0) * 100}%` }} /></i><em>{percent(item.ratio)}</em></label>)}</div> : <div className="inline-empty">暂无可识别持仓</div>}</article>
                <article><h4>近30天行为</h4><div className="stats"><div><b>{behavior.recent_30d_counts.login}</b><span>登录</span></div><div><b>{behavior.recent_30d_counts.consult}</b><span>咨询</span></div><div><b>{behavior.recent_30d_counts.complaint}</b><span>投诉</span></div></div></article>
                <article className="asset-metric"><h4>资产画像指标</h4><dl><div><dt>持仓产品</dt><dd>{asset.holding_product_count} 款</dd></div><div><dt>高流动性比例</dt><dd>{percent(asset.high_liquidity_ratio)}</dd></div><div><dt>加权预期收益</dt><dd>{percent(asset.weighted_expected_return)}</dd></div><div><dt>持仓覆盖率</dt><dd>{basic.aum > 0 ? percent(asset.holding_amount / basic.aum) : "—"}</dd></div></dl></article>
                <article className="asset-metric"><h4>最近行为</h4><dl><div><dt>最近事件</dt><dd>{behavior.latest_event_type || "暂无"}</dd></div><div><dt>事件日期</dt><dd>{behavior.latest_event_date || "暂无"}</dd></div><div><dt>历史登录</dt><dd>{behavior.total_counts.login} 次</dd></div><div><dt>历史咨询</dt><dd>{behavior.total_counts.consult} 次</dd></div></dl></article>
              </div>}
              {customerTab === "holding" && <div className="table"><table><thead><tr>{["产品", "类型", "风险", "持仓金额", "流动性", "预期收益", "购买日期"].map(header => <th key={header}>{header}</th>)}</tr></thead><tbody>{asset.holdings.map(holding => <tr key={holding.holding_id}><td><b>{holding.product_id}</b><small>{holding.product_name}</small></td><td>{holding.product_type}</td><td><span className="risk-tag">{holding.risk_level}</span></td><td>{money(holding.amount)}</td><td>{holding.liquidity}</td><td>{percent(holding.expected_return)}</td><td>{holding.buy_date}</td></tr>)}</tbody></table>{asset.holdings.length === 0 && <div className="empty-result"><b>暂无持仓记录</b><span>该客户当前没有可识别的产品持仓。</span></div>}</div>}
              {customerTab === "behavior" && <div className="behavior-panel"><div className="behavior-metrics">{[["登录", behavior.total_counts.login, behavior.recent_30d_counts.login], ["咨询", behavior.total_counts.consult, behavior.recent_30d_counts.consult], ["投诉", behavior.total_counts.complaint, behavior.recent_30d_counts.complaint]].map(item => <article key={item[0]}><small>{item[0]}</small><strong>{item[1]}</strong><span>近30天 {item[2]} 次</span></article>)}</div><div className="latest-event"><b>最近一次行为</b><span>{behavior.latest_event_type ? `${behavior.latest_event_type} · ${behavior.latest_event_date}` : "暂无行为记录"}</span></div><div className="tags">{behavior.tags.map(tag => <i key={tag}>{tag}</i>)}</div></div>}
            </div>
            <aside className="ai-card"><div className="ai-title"><b>AI</b><span><strong>客户洞察</strong><small>基于结构化画像生成并保存</small></span></div>{aiBusy ? <div className="loading">正在调用画像总结服务…</div> : (profile.ai_summary ? <AiAnalysisPanel analysis={profile.ai_summary} /> : <div className="ai-empty">该客户尚未生成画像总结。点击下方按钮后，系统会形成画像概述、需求洞察和服务建议。</div>)}{aiError && <div className="ai-error">{aiError}</div>}<div className="evidence"><small>引用依据</small><span>风险偏好 {basic.risk_appetite} · {basic.risk_label}</span><span>持仓产品 {asset.holding_product_count} 款</span><span>高流动性比例 {percent(asset.high_liquidity_ratio)}</span>{profile.ai_summary_generated_at && <span>生成时间 {new Date(profile.ai_summary_generated_at).toLocaleString("zh-CN")}</span>}</div><button disabled={aiBusy} onClick={refreshAiSummary}>↻ {profile.ai_summary ? "重新生成总结" : "生成画像总结"}</button><em>{summaryProvider ? `${summaryProvider} · ` : ""}AI内容仅供辅助分析</em></aside>
          </div>
        </>}
      </>}
    </section>

    {createOpen && <div className="modal-backdrop" role="button" tabIndex={0} aria-label="关闭新建客户对话框" onKeyDown={event => { if (event.key === "Escape" && !createBusy) setCreateOpen(false); }} onMouseDown={event => { if (event.target === event.currentTarget && !createBusy) setCreateOpen(false); }}><section className="customer-modal" role="dialog" aria-modal="true" aria-labelledby="create-customer-title"><button className="close" aria-label="关闭" onClick={() => setCreateOpen(false)}>×</button><header><small>NEW CUSTOMER</small><h2 id="create-customer-title">新建客户并自动评估风险</h2><p>客户编号由后端生成，风险等级由规则服务计算。</p></header><form onSubmit={submitCustomer}><div className="form-grid"><label>年龄段<select value={createForm.age_group} onChange={event => setCreateForm({ ...createForm, age_group: event.target.value })}>{ageGroups.map(value => <option key={value}>{value}</option>)}</select></label><label>城市<input required maxLength={50} value={createForm.city} onChange={event => setCreateForm({ ...createForm, city: event.target.value })} /></label><label>职业<select value={createForm.occupation} onChange={event => setCreateForm({ ...createForm, occupation: event.target.value })}>{occupations.map(value => <option key={value}>{value}</option>)}</select></label><label>收入区间<select value={createForm.income_level} onChange={event => setCreateForm({ ...createForm, income_level: event.target.value })}>{incomeLevels.map(value => <option key={value}>{value}</option>)}</select></label><label>注册日期<input required type="date" max={new Date().toISOString().slice(0, 10)} value={createForm.register_date} onChange={event => setCreateForm({ ...createForm, register_date: event.target.value })} /></label><label>资产管理规模（元）<input required type="number" min="0" step="0.01" value={createForm.aum} onChange={event => setCreateForm({ ...createForm, aum: event.target.value })} /></label><label>客户等级<select value={createForm.vip_level} onChange={event => setCreateForm({ ...createForm, vip_level: event.target.value })}>{vipLevels.map(value => <option key={value}>{value}</option>)}</select></label><label className="switch-label">App状态<span><input type="checkbox" checked={createForm.has_app} onChange={event => setCreateForm({ ...createForm, has_app: event.target.checked })} /> 已安装 App</span></label></div>{createError && <div className="form-error">{createError}</div>}<footer><button type="button" className="secondary" disabled={createBusy} onClick={() => setCreateOpen(false)}>取消</button><button type="submit" className="primary" disabled={createBusy}>{createBusy ? "正在创建并评估…" : "创建客户并评估风险"}</button></footer></form></section></div>}
  </>;
}
