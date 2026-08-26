"use client";

import { useMemo, useRef, useState } from "react";
import CustomerModule from "./customer-module";

type Module = "customer" | "advisor" | "marketing" | "dashboard";

const sources = [
  ["客", "客户数据", "t_customer.csv", "8,000"],
  ["产", "产品数据", "t_product.csv", "30"],
  ["持", "持仓数据", "t_holding.csv", "8,579"],
  ["行", "行为数据", "t_event.csv", "13,142"],
  ["营", "营销数据", "t_campaign.csv", "50,000"],
];

const customers = [
  { id: "C002583", age: "18–24岁", city: "南京", occupation: "其他", income: "10–30万", registered: "2020-05-25", aum: 100631.23, risk: "R4", vip: "普通客户", app: true, active: "中等活跃" },
  { id: "C000001", age: "45–54岁", city: "南京", occupation: "企业职员", income: "10–30万", registered: "2021-03-03", aum: 96618.43, risk: "R1", vip: "银卡客户", app: false, active: "低活跃" },
  { id: "C000002", age: "35–44岁", city: "杭州", occupation: "退休", income: "30–50万", registered: "2022-08-13", aum: 1151110.45, risk: "R2", vip: "普通客户", app: true, active: "高活跃" },
  { id: "C000003", age: "55–64岁", city: "上海", occupation: "其他", income: "10万以下", registered: "2018-09-29", aum: 21333.76, risk: "R1", vip: "普通客户", app: true, active: "低活跃" },
  { id: "C000005", age: "25–34岁", city: "上海", occupation: "退休", income: "30–50万", registered: "2019-09-26", aum: 253755.96, risk: "R3", vip: "普通客户", app: true, active: "中等活跃" },
  { id: "C000006", age: "65岁以上", city: "南京", occupation: "其他", income: "30–50万", registered: "2019-11-01", aum: 283614.00, risk: "R5", vip: "普通客户", app: true, active: "高活跃" },
  { id: "C000008", age: "55–64岁", city: "常州", occupation: "个体经营", income: "30–50万", registered: "2018-06-28", aum: 507112.51, risk: "R5", vip: "金卡客户", app: true, active: "中等活跃" },
  { id: "C000015", age: "35–44岁", city: "常州", occupation: "退休", income: "10万以下", registered: "2021-11-13", aum: 33631.62, risk: "R3", vip: "钻石客户", app: true, active: "低活跃" },
] as const;

const riskNames: Record<string, string> = { R1: "保守型", R2: "稳健型", R3: "平衡型", R4: "成长型", R5: "进取型" };

const opportunities = [
  ["C002583", "P005 现金管理005号", "App推送", "86.7%", "高意向"],
  ["C003040", "P012 混合012号", "客户经理", "79.4%", "高意向"],
  ["C000656", "P011 固定期限011号", "电话", "72.8%", "高意向"],
  ["C005578", "P002 固定期限002号", "短信", "64.2%", "中意向"],
  ["C002962", "P009 现金管理009号", "客户经理", "51.6%", "中意向"],
];

const allocations = [
  ["P011", "固定期限011号", "R2", 24, "¥120,000", "T+0"],
  ["P012", "混合012号", "R2", 22, "¥110,000", "T+1"],
  ["P006", "混合006号", "R3", 18, "¥90,000", "T+1"],
  ["P015", "固定期限015号", "R4", 16, "¥80,000", "封闭"],
  ["P010", "现金管理010号", "R1", 12, "¥60,000", "T+0"],
] as const;

const strategies = [
  [1, "P005", "现金管理005号", "R5", "10.97%", "App推送", "工作日18:00–21:00", "客户风险承受能力较高，且历史 App 推送响应表现良好。"],
  [2, "P015", "固定期限015号", "R4", "6.70%", "客户经理", "工作日12:00–14:00", "风险等级匹配，可作为当前组合中的收益增强配置。"],
  [3, "P006", "混合006号", "R3", "5.13%", "App推送", "周末14:00–18:00", "T+1流动性较好，可降低当前持仓集中度。"],
] as const;

function Status({ children, warn = false }: { children: React.ReactNode; warn?: boolean }) {
  return <span className={warn ? "status warn" : "status"}><i />{children}</span>;
}

function Metric({ label, value, note, gold = false }: { label: string; value: string; note: string; gold?: boolean }) {
  return <div className={gold ? "metric gold" : "metric"}><small>{label}</small><strong>{value}</strong><span>{note}</span></div>;
}

export default function Home() {
  const [active, setActive] = useState<Module>("customer");
  const [customerTab, setCustomerTab] = useState("overview");
  const [marketingTab, setMarketingTab] = useState("a1");
  const [drawer, setDrawer] = useState(false);
  const [fileName, setFileName] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiAlt, setAiAlt] = useState(false);
  const [runState, setRunState] = useState("待运行");
  const [liquidity, setLiquidity] = useState(20);
  const [tracking, setTracking] = useState(1);
  const [customerQuery, setCustomerQuery] = useState("");
  const [riskFilter, setRiskFilter] = useState("全部风险");
  const [cityFilter, setCityFilter] = useState("全部城市");
  const [selectedCustomerId, setSelectedCustomerId] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const cash = useMemo(() => 8 + Math.max(0, Math.round((liquidity - 20) / 5)), [liquidity]);
  const filteredCustomers = useMemo(() => {
    const query = customerQuery.trim().toLowerCase();
    return customers.filter(customer => {
      const fuzzyMatch = !query || [customer.id, customer.city, customer.occupation, customer.vip, customer.risk, customer.age].some(value => value.toLowerCase().includes(query));
      return fuzzyMatch && (riskFilter === "全部风险" || customer.risk === riskFilter) && (cityFilter === "全部城市" || customer.city === cityFilter);
    });
  }, [customerQuery, riskFilter, cityFilter]);
  const selectedCustomer = customers.find(customer => customer.id === selectedCustomerId) ?? null;

  const titles = { customer: "客户画像与风险评估", advisor: "智能投顾推荐", marketing: "营销运营工作台", dashboard: "经营可视化看板" };
  const descriptions = {
    customer: "统一接入客户、产品、持仓、行为及营销数据，形成可追溯的客户全景视图。",
    advisor: "基于投资场景与约束，生成可解释、可校验的产品组合配置方案。",
    marketing: "导入待分析名单，查看响应概率、Top 3营销策略及简化执行状态。",
    dashboard: "汇总客户、营销和资产配置结果，快速掌握数据质量与经营机会。",
  };

  function runAnalysis() {
    setRunState("正在关联画像与生成策略…");
    window.setTimeout(() => setRunState("分析完成"), 1200);
  }

  function pageHead(action?: React.ReactNode) {
    return <div className="page-head"><div><h1>{titles[active]}</h1><p>{descriptions[active]}</p></div>{action}</div>;
  }

  function customerPage() {
    if (active === "customer") return <CustomerModule />;
    return <>
      {pageHead(<button className="primary import-button" onClick={() => fileRef.current?.click()}>⇧&nbsp; 导入业务数据</button>)}
      <input ref={fileRef} hidden type="file" accept=".csv" onChange={e => setFileName(e.target.files?.[0]?.name || "")} />
      {fileName && <div className="notice"><b>✓</b><span><strong>{fileName}</strong> 字段识别完成，已进入导入校验队列。</span><button onClick={() => setFileName("")}>关闭</button></div>}
      <section className="card block">
        <div className="section-head"><div><h2>数据总览</h2><p>五类业务数据已完成关联，可随时替换或补充导入。</p></div><Status>数据截至 2026-03-31</Status></div>
        <div className="source-grid">{sources.map((s, i) => <button className="source" key={s[1]} onClick={() => fileRef.current?.click()}><b className={`s${i}`}>{s[0]}</b><span><strong>{s[1]}</strong><em>{s[3]} <small>条记录</small></em><Status>已导入</Status></span></button>)}</div>
      </section>
      <section className="card block customer-records">
        <div className="section-head"><div><h2>{selectedCustomer ? "客户档案详情" : "客户档案"}</h2><p>{selectedCustomer ? "查看客户画像、风险等级及关联业务记录。" : "通过客户编号、城市或职业快速检索，并从列表进入客户详情。"}</p></div>{selectedCustomer && <button className="secondary" onClick={() => { setSelectedCustomerId(null); setCustomerTab("overview"); }}>← 返回客户列表</button>}</div>
        {!selectedCustomer && <>
          <div className="customer-toolbar">
            <label className="customer-search"><span>⌕</span><input aria-label="模糊搜索客户" value={customerQuery} onChange={event => setCustomerQuery(event.target.value)} placeholder="搜索客户编号、城市、职业、等级或风险偏好" />{customerQuery && <button aria-label="清空搜索" onClick={() => setCustomerQuery("")}>×</button>}</label>
            <select aria-label="按风险等级筛选" value={riskFilter} onChange={event => setRiskFilter(event.target.value)}>{["全部风险", "R1", "R2", "R3", "R4", "R5"].map(option => <option key={option}>{option}</option>)}</select>
            <select aria-label="按城市筛选" value={cityFilter} onChange={event => setCityFilter(event.target.value)}>{["全部城市", "南京", "杭州", "上海", "常州"].map(option => <option key={option}>{option}</option>)}</select>
            <button className="reset-filter" onClick={() => { setCustomerQuery(""); setRiskFilter("全部风险"); setCityFilter("全部城市"); }}>重置条件</button>
          </div>
          <div className="customer-result-meta"><span>共 <b>8,000</b> 位客户，当前显示 <b>{filteredCustomers.length}</b> 条演示数据</span><small>支持模糊匹配</small></div>
          <div className="table customer-table"><table><thead><tr>{["客户编号", "客户等级", "年龄段 / 城市", "职业", "资产管理规模", "风险偏好", "App状态", "活跃度", ""].map(header => <th key={header}>{header}</th>)}</tr></thead><tbody>{filteredCustomers.map(customer => <tr key={customer.id} tabIndex={0} onClick={() => setSelectedCustomerId(customer.id)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") setSelectedCustomerId(customer.id); }}><td><div className="customer-id"><i>{customer.id.slice(-2)}</i><b>{customer.id}</b></div></td><td><span className="vip-tag">{customer.vip}</span></td><td><b>{customer.age}</b><small>{customer.city}</small></td><td>{customer.occupation}</td><td className="money-cell">¥ {customer.aum.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}</td><td><span className={`risk-pill ${customer.risk.toLowerCase()}`}>{customer.risk}</span><small>{riskNames[customer.risk]}</small></td><td><span className={customer.app ? "app-state on" : "app-state"}>{customer.app ? "已安装" : "未安装"}</span></td><td><Status warn={customer.active === "低活跃"}>{customer.active}</Status></td><td><button className="row-action" aria-label={`查看${customer.id}客户详情`}>查看 ›</button></td></tr>)}</tbody></table>{filteredCustomers.length === 0 && <div className="empty-result"><b>未找到匹配客户</b><span>请尝试缩短关键词或重置筛选条件。</span></div>}</div>
          <div className="customer-pagination"><span>每页 20 条</span><div><button disabled>‹</button><button className="on">1</button><button>2</button><button>3</button><i>…</i><button>400</button><button>›</button></div></div>
        </>}
        {selectedCustomer && <>
        <div className="profile-bar"><div className="avatar">{selectedCustomer.id.slice(-2)}</div><div className="profile-info"><div><h3>{selectedCustomer.id}</h3><span>{selectedCustomer.vip}</span><Status warn={selectedCustomer.active === "低活跃"}>{selectedCustomer.active}</Status></div><p>{selectedCustomer.age} · {selectedCustomer.city} · {selectedCustomer.occupation} · 收入{selectedCustomer.income}</p><div className="tags"><i>已实名</i><i>{selectedCustomer.app ? "App已安装" : "App未安装"}</i><i>存量客户</i></div></div><div className="aum"><small>资产管理规模</small><strong>¥ {selectedCustomer.aum.toLocaleString("zh-CN", { minimumFractionDigits: 2 })}</strong><span>持仓产品 2 款</span></div><div className="risk"><small>风险偏好</small><strong>{selectedCustomer.risk}</strong><span>{riskNames[selectedCustomer.risk]}</span></div></div>
        <div className="profile-grid">
          <div className="card inner">
            <div className="tabs">{[["overview","画像概览"],["holding","资产持仓"],["event","行为轨迹"],["campaign","营销历史"]].map(t => <button key={t[0]} className={customerTab===t[0]?"on":""} onClick={() => setCustomerTab(t[0])}>{t[1]}</button>)}</div>
            {customerTab === "overview" && <div className="overview"><article><h4>基础信息</h4><dl><div><dt>年龄段</dt><dd>{selectedCustomer.age}</dd></div><div><dt>城市</dt><dd>{selectedCustomer.city}</dd></div><div><dt>职业</dt><dd>{selectedCustomer.occupation}</dd></div><div><dt>注册日期</dt><dd>{selectedCustomer.registered}</dd></div></dl></article><article><h4>风险信息</h4><div className="risk-row"><b>{selectedCustomer.risk}</b><span>{riskNames[selectedCustomer.risk]}<small>历史风险测评结果</small></span></div><div className="risk-scale"><i/><i/><i/><i/><em/></div><p>来源：历史风险测评 · 截至 2026-03-31</p></article><article><h4>资产结构</h4><div className="mini-bars"><label>混合产品<i><b style={{width:"68%"}}/></i><em>68%</em></label><label>定开产品<i><b style={{width:"32%"}}/></i><em>32%</em></label></div></article><article><h4>近期活跃</h4><div className="stats"><div><b>{selectedCustomer.active === "高活跃" ? 12 : selectedCustomer.active === "中等活跃" ? 4 : 1}</b><span>近90天登录</span></div><div><b>0</b><span>近期咨询</span></div><div><b>0</b><span>近期投诉</span></div></div></article></div>}
            {customerTab === "holding" && <Table headers={["产品","类型","风险","持仓金额","购买日期"]} rows={[["P012 混合012号","混合","R2","¥20,259.03","2025-08-24"],["P018 定开018号","定开","R3","¥42,550.10","2024-07-04"]]} />}
            {customerTab === "event" && <Timeline items={[["客户登录App","2025-10-08","常规登录行为，未产生咨询。"],["查看产品详情","2025-08-29","浏览定开类产品页面约3分钟。"],["完成产品购买","2025-08-24","买入混合012号 ¥20,259.03。"]]} />}
            {customerTab === "campaign" && <Table headers={["日期","产品","渠道","结果"]} rows={[["2026-02-15","P001 混合001号","客户经理","未响应"],["2026-01-23","P008 定开008号","App推送","已响应"],["2025-12-15","P029","客户经理","已响应"]]} />}
          </div>
          <aside className="ai-card"><div className="ai-title"><b>AI</b><span><strong>客户洞察</strong><small>基于结构化数据生成</small></span></div>{aiBusy?<div className="loading">正在归纳客户画像…</div>:<p>{aiAlt?`该客户资产规模约${Math.round(selectedCustomer.aum / 10000)}万元，当前风险偏好为${riskNames[selectedCustomer.risk]}。建议结合活跃度与渠道状态安排后续触达。`:`该客户风险偏好为${riskNames[selectedCustomer.risk]}，现有持仓集中度需要持续关注。建议优先推荐风险匹配、流动性适中的产品。`}</p>}<div className="evidence"><small>引用依据</small><span>风险偏好 {selectedCustomer.risk}</span><span>{selectedCustomer.app ? "App渠道可触达" : "App渠道暂不可用"}</span><span>客户活跃度：{selectedCustomer.active}</span></div><button onClick={() => {setAiBusy(true);setTimeout(()=>{setAiBusy(false);setAiAlt(!aiAlt)},800)}}>↻ 重新生成总结</button><em>AI生成内容仅供辅助分析</em></aside>
        </div>
        </>}
      </section>
    </>;
  }

  function advisorPage() {
    return <>
      {pageHead(<Status>Part B · 20个场景</Status>)}
      <div className="advisor-layout">
        <aside className="card parameters"><div className="section-head"><h2><i>01</i> 配置条件</h2><button>恢复参数</button></div><label>投资场景<select><option>S01</option><option>S02</option><option>S03</option></select></label><label>可配置总金额<div className="money">¥ <input value="500,000" readOnly /></div></label><div className="two"><label>风险厌恶系数<input value="0.94" readOnly /></label><label>最低持仓数<input value="4" readOnly /></label></div><label>单产品权重上限 <b>30%</b><input type="range" value="30" readOnly /></label><label>高风险产品上限 <b>50%</b><input type="range" value="50" readOnly /></label><label>最低流动性要求 <b>{liquidity}%</b><input type="range" min="10" max="60" step="5" value={liquidity} onChange={e=>setLiquidity(Number(e.target.value))}/></label><div className="hint"><b>场景解释</b><p>当前方案偏向收益与风险平衡，允许适度配置高风险产品，并保留至少{liquidity}%高流动性资产。</p></div><button className="primary full">生成配置方案 →</button></aside>
        <main className="result-col">
          <section className="card result"><div className="section-head"><h2><i>02</i> 配置结果</h2><Status>全部约束通过</Status></div><div className="metrics"><Metric label="预期年化收益" value="5.42%" note="较基准 +0.68%" gold/><Metric label="组合波动率" value="4.18%" note="风险水平适中"/><Metric label="组合效用 U" value="0.0149" note="当前场景近优解"/><Metric label="现金比例" value={`${cash}%`} note={`流动性要求 ${liquidity}%`}/></div><div className="allocation"><div className="donut"><span><b>¥50万</b><small>总配置金额</small></span></div><div className="legend">{allocations.map((a,i)=><div key={a[0]}><i className={`c${i}`}/><span>{a[1]}</span><b>{a[3]}%</b></div>)}<div><i className="cash"/><span>现金</span><b>{cash}%</b></div></div></div></section>
          <section className="card result"><div className="section-head"><h2>产品配置明细</h2><button className="secondary">导出配置结果</button></div><div className="table"><table><thead><tr>{["产品","风险","配置比例","配置金额","流动性"].map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{allocations.map(a=><tr key={a[0]}><td><b>{a[0]}</b> {a[1]}</td><td><span className="risk-tag">{a[2]}</span></td><td><div className="weight"><i><b style={{width:`${Number(a[3])*3}%`}}/></i>{a[3]}%</div></td><td>{a[4]}</td><td>{a[5]}</td></tr>)}</tbody></table></div></section>
          <section className="card result"><div className="section-head"><h2>约束检查</h2><Status>5 / 5 通过</Status></div><div className="constraints">{[["产品权重总和","≤100%",`${100-cash}%`],["单产品最高比例","≤30%","24%"],["高风险产品比例","≤50%","16%"],["高流动性资产",`≥${liquidity}%`,`${38+cash}%`],["持仓产品数量","≥4款","5款"]].map(c=><div key={c[0]}><b>✓</b><span><strong>{c[0]}</strong><small>要求 {c[1]}</small></span><em>{c[2]}</em></div>)}</div></section>
        </main>
      </div>
    </>;
  }

  function marketingPage() {
    return <>
      {pageHead(<button className="primary" onClick={runAnalysis}>＋ 新建营销分析</button>)}
      <section className="card batch"><div><b>批</b><span><strong>2026年4月财富客户营销分析</strong><small>任务 MKT-20260415 · 策略日期 2026-04-15</small></span></div><div className="file-box"><b>A1</b><span><strong>partA_test_contacts.csv</strong><small>8,000条记录</small></span><Status>校验通过</Status></div><div className="file-box"><b>A2</b><span><strong>partA_strategy_customers.csv</strong><small>2,000名客户</small></span><Status>校验通过</Status></div><button className="secondary" onClick={runAnalysis}>{runState}</button>{runState.includes("正在")&&<i className="progress"/>}</section>
      <div className="main-tabs">{[["a1","A1 响应预测","8,000"],["a2","A2 Top 3策略","2,000"],["track","执行追踪","126"]].map(t=><button className={marketingTab===t[0]?"on":""} key={t[0]} onClick={()=>setMarketingTab(t[0])}>{t[1]} <span>{t[2]}</span></button>)}</div>
      {marketingTab === "a1" && <section className="card marketing"><div className="metrics"><Metric label="高意向客户" value="1,286" note="预测概率≥70%" gold/><Metric label="平均响应概率" value="48.6%" note="全量8,000条"/><Metric label="推荐App推送" value="42.8%" note="渠道占比最高"/><Metric label="名单覆盖率" value="100%" note="无缺失或重复"/></div><div className="toolbar"><input placeholder="搜索客户ID或产品"/><select><option>全部渠道</option></select><select><option>全部意向等级</option></select><button className="secondary">导出预测结果</button></div><div className="table"><table><thead><tr>{["客户","推荐产品","渠道","触达日期","响应概率","意向等级",""].map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{opportunities.map(o=><tr key={o[0]} onClick={()=>setDrawer(true)}><td><b>{o[0]}</b><small>R4 · 普通客户</small></td><td>{o[1]}</td><td>{o[2]}</td><td>2026-04-15</td><td><div className="prob"><b>{o[3]}</b><i><em style={{width:o[3]}}/></i></div></td><td><span className={o[4]==="高意向"?"intent high":"intent"}>{o[4]}</span></td><td>›</td></tr>)}</tbody></table></div></section>}
      {marketingTab === "a2" && <section><div className="card customer-strip"><div className="avatar">83</div><span><small>当前目标客户</small><strong>C002583</strong><em>R4成长型 · AUM ¥100,631 · App已安装</em></span><button className="secondary" onClick={()=>setDrawer(true)}>查看客户画像</button></div><div className="strategy-grid">{strategies.map(s=><article className="card strategy" key={s[0]}><div className="rank">TOP {s[0]} <span>推荐得分 {94-Number(s[0])*5}</span></div><div className="product"><span><small>{s[1]}</small><strong>{s[2]}</strong></span><em><b>{s[3]}</b><strong>{s[4]}</strong><small>预期年化</small></em></div><div className="strategy-meta"><span><small>推荐渠道</small><b>{s[5]}</b></span><span><small>推荐时间</small><b>{s[6]}</b></span></div><div className="reason"><small>推荐依据</small><p>{s[7]}</p></div><div className="script"><small>营销话术</small><p>您好，结合您的风险偏好与当前持仓结构，为您精选了这款产品，欢迎了解详情。</p></div><button onClick={()=>setDrawer(true)}>查看完整策略依据 →</button></article>)}</div></section>}
      {marketingTab === "track" && <div className="tracking"><section className="card"><div className="section-head"><h2>策略执行进度</h2><Status>Demo演示数据</Status></div><div className="steps">{[["待执行","84"],["已触达","29"],["已响应","10"],["已购买","3"]].map((s,i)=><div className={tracking>=i?"on":""} key={s[0]}><i>{i+1}</i><b>{s[1]}</b><span>{s[0]}</span></div>)}</div><div className="execution"><span className="avatar">83</span><p><b>C002583 · P005</b><small>App推送 · 工作日18:00–21:00</small></p><div><button className={tracking>=1?"done":""}>✓ 已触达</button><button className={tracking>=2?"done":""} onClick={()=>setTracking(2)}>记录响应</button><button className={tracking>=3?"done":""} onClick={()=>setTracking(3)}>标记购买</button></div></div></section><section className="card"><h2>执行时间线</h2><Timeline items={[["策略生成完成","04-15 10:20","已生成Top 3营销策略。"],["客户经理确认","04-15 11:05","确认使用首选策略。"],["App推送触达",tracking>=1?"04-15 18:30":"待执行","通过App发送营销信息。"],["客户响应",tracking>=2?"04-16 09:15":"等待反馈",tracking>=2?"客户表示有兴趣。":"尚未记录客户反馈。"]]} /></section></div>}
    </>;
  }

  function dashboardPage() {
    return <>
      {pageHead(<span className="date-chip">统计周期：截至 2026-03-31</span>)}
      <div className="dashboard-kpis"><Metric label="客户总数" value="8,000" note="覆盖5个主要城市"/><Metric label="客户总AUM" value="¥41.8亿" note="户均52.3万元" gold/><Metric label="高意向机会" value="1,286" note="占预测名单16.1%"/><Metric label="历史营销响应率" value="13.7%" note="共50,000次触达"/><Metric label="可行配置场景" value="20/20" note="全部约束通过"/></div>
      <div className="dashboard"><section className="card chart wide"><div className="section-head"><div><h2>客户资产与风险分布</h2><p>按风险偏好展示客户数量</p></div></div><div className="bars">{[["R1",58,"1,326"],["R2",84,"1,904"],["R3",100,"2,286"],["R4",72,"1,644"],["R5",37,"840"]].map((b,i)=><div key={b[0]}><em>{b[2]}</em><i style={{height:`${b[1]}%`}} className={i===2?"goldbar":""}/><b>{b[0]}</b><span>{["保守","稳健","平衡","成长","进取"][i]}</span></div>)}</div></section><section className="card chart"><h2>客户等级分布</h2><div className="vip-chart"><div className="donut vip"><span><b>8,000</b><small>客户总数</small></span></div><div className="legend vip-legend"><div><i className="c0"/>普通客户 <b>52%</b></div><div><i className="c1"/>银卡客户 <b>25%</b></div><div><i className="c3"/>金卡客户 <b>16%</b></div><div><i className="cash"/>钻石客户 <b>7%</b></div></div></div></section><section className="card chart"><h2>营销渠道表现</h2><div className="channel">{[["App推送",68,"18.4%"],["客户经理",55,"15.1%"],["电话",39,"11.6%"],["短信",31,"9.8%"]].map(c=><div key={c[0]}><span>{c[0]}</span><i><b style={{width:`${c[1]}%`}}/></i><em>{c[2]}</em></div>)}</div><p className="insight"><b>洞察</b> App推送为当前响应率最高渠道，建议优先覆盖已安装App且近期活跃客户。</p></section><section className="card chart"><h2>A1预测机会分布</h2><div className="stack"><i style={{width:"16%"}}>16%</i><i style={{width:"44%"}}>44%</i><i style={{width:"40%"}}>40%</i></div><div className="intent-list"><span>高意向 <b>1,286</b></span><span>中意向 <b>3,514</b></span><span>低意向 <b>3,200</b></span></div></section><section className="card chart wide"><div className="section-head"><h2>智能能力运行概览</h2><Status>运行正常</Status></div><div className="engines">{[["A1","响应预测","8,000/8,000"],["A2","Top 3策略","2,000/2,000"],["B","组合配置","20/20场景"]].map(e=><div key={e[0]}><b>{e[0]}</b><span><strong>{e[1]}</strong><small>{e[2]}</small></span><em>100%</em></div>)}</div></section></div>
    </>;
  }

  return <div className="app">
    <aside className="sidebar"><div className="brand"><b>兴</b><span><strong>智能财富管理</strong><small>运营平台</small></span></div><nav>{[["customer","客","客户画像","数据接入与风险评估"],["advisor","投","智能投顾","组合配置与约束检查"],["marketing","营","营销运营","响应预测与策略生成"],["dashboard","览","经营看板","关键指标与结果汇总"]].map(n=><button key={n[0]} className={active===n[0]?"on":""} onClick={()=>setActive(n[0] as Module)}><b>{n[1]}</b><span><strong>{n[2]}</strong><small>{n[3]}</small></span></button>)}</nav><div className="safe"><b>盾</b><span><strong>数据安全域</strong><small>演示环境 · 已脱敏</small></span></div></aside>
    <div className="main"><header><div>智能财富管理运营平台 <i>›</i> <b>{titles[active]}</b></div><section><span><small>分析基准日</small><b>2026-03-31</b></span><div className="user">李</div><span><b>李经理</b><small>财富运营部</small></span></section></header><main className={`page-${active}`}>{active==="customer"?customerPage():active==="advisor"?advisorPage():active==="marketing"?marketingPage():dashboardPage()}</main><footer>智能财富管理运营平台 · Demo V1 <span>客户画像模块已接入实时 API · 其他模块为演示数据</span></footer></div>
    {drawer&&<div className="backdrop" onClick={()=>setDrawer(false)}><aside className="drawer" onClick={e=>e.stopPropagation()}><button className="close" onClick={()=>setDrawer(false)}>×</button><label>CUSTOMER 360</label><div className="drawer-profile"><div className="avatar">83</div><span><h2>C002583</h2><p>普通客户 · R4成长型 · 南京</p></span></div><div className="drawer-kpis"><Metric label="AUM" value="¥10.06万" note="当前资产"/><Metric label="历史响应率" value="50.0%" note="12次触达"/><Metric label="持仓产品" value="2款" note="集中度偏高"/></div><section><h3>客户标签</h3><div className="tags"><i>成长型</i><i>App已安装</i><i>偏好线上渠道</i><i>持仓集中</i></div></section><section className="drawer-ai"><b>AI</b><p>该客户风险承受能力较高，历史上对App推送响应良好，适合优先推荐具有收益弹性且能改善持仓集中度的产品。</p></section><section><h3>本次营销机会</h3><dl><div><dt>推荐产品</dt><dd>P005 现金管理005号</dd></div><div><dt>响应概率</dt><dd>86.7%</dd></div><div><dt>推荐渠道</dt><dd>App推送</dd></div><div><dt>数据截点</dt><dd>2026-04-15</dd></div></dl></section><section><h3>推荐依据</h3><ul><li>风险偏好与产品风险等级匹配</li><li>历史App推送响应优于其他渠道</li><li>现有持仓存在分散配置空间</li></ul></section><button className="primary full" onClick={()=>{setDrawer(false);setActive("marketing");setMarketingTab("a2")}}>查看 Top 3 营销策略</button></aside></div>}
  </div>;
}

function Table({headers,rows}:{headers:string[],rows:string[][]}) { return <div className="table"><table><thead><tr>{headers.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={i}>{r.map((c,j)=><td key={j}>{c}</td>)}</tr>)}</tbody></table></div> }
function Timeline({items}:{items:string[][]}) { return <div className="timeline">{items.map((i,n)=><div key={n}><b>{i[0]}</b><span>{i[1]}</span><p>{i[2]}</p></div>)}</div> }
