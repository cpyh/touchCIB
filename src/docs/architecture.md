# 智能财富管理运营平台 · 系统架构设计

> 版本：v1.0（2026-03 分析基准日口径）
> 状态图例：✅ 已实现并验证 ｜ 🟡 设计已定、待实现 ｜ ⬜ 待设计

---

## 1. 架构目标

以「两条核心数据链路 + 一个运营平台」为主线：

1. **营销链路（Part A）**：营销响应预测（A1）→ 营销策略生成（A2），支撑精细化营销触达；
2. **投顾链路（Part B）**：组合配置优化，支撑智能投顾；
3. **平台底座（Part C/D）**：数据分层架构、规则/流程引擎、HTTP 服务、运营可视化看板。

设计原则：

- **可复现**：`random_state=42` 固定随机过程；训练/推理共用同一特征构建器；模型/特征版本双重校验；
- **可解释**：预测有局部解释、策略有规则轨迹、优化有全局最优性证书；
- **防泄漏**：所有特征严格 as-of 截断，时间留出验证；
- **可运营**：规则可配置、可开关、可追溯，运营人员在看板上可干预。

---

## 2. 题目模块与系统组件映射

| 题目模块 | 分值性质 | 系统组件 | 状态 |
|----------|----------|----------|------|
| A1 营销响应预测 | 30 分自动 | `src/partA1serving/`（训练、特征、在线推理） | ✅ |
| A2 营销策略生成 | 5 分自动 + D 验收 | A1 概率排序 + 规则过滤 + ADS 日批 | ✅ |
| B 投资组合优化 | 15 分自动 | `src/algorithms/partb.py`（核心）、`src/pipelines/solve_partB.py`（CLI）、`src/portfolio.py` | ✅ |
| C 系统架构与工程 | 人工 | 数据分层（ODS→DWD→DWS→ADS）、Flask 服务、质量检查、测试、规则/流程引擎 | ✅ |
| D 平台演示与看板 | 人工 | 四页看板（进件评估 / 智能投顾 / 营销运营 / 可视化） | ✅ |
| 加分创新 | 人工 | 全局最优性证书、局部解释、规则轨迹、特征/模型版本管理 | ✅ |

---

## 3. 总体架构

```mermaid
flowchart TB
    subgraph APP["应用层（运营人员，官方四 Tab）"]
        T1["Tab1 客户进件与风险评估"]
        T2["Tab2 智能投顾推荐"]
        T3["Tab3 营销运营工作台<br/>概率 · Top3 · 规则轨迹"]
        T4["Tab4 可视化看板<br/>KPI · 分布 · 漏斗"]
    end

    subgraph SVC["服务层（Flask, 0.0.0.0:5001）"]
        API["REST API"]
        CUS["/customers/&lt;id&gt;/profile"]
        PF["/portfolio/optimize<br/>/portfolio/scenarios"]
        MK["/marketing/tasks<br/>/customers/&lt;id&gt;/strategies"]
    end

    subgraph ALG["算法层（离线/在线可切换）"]
        A1F["A1 特征构建器<br/>as-of 严格截断"]
        A1M["A1 模型<br/>LightGBM 主模型 + LR 基线"]
        A1I["A1 推理 + 局部解释"]
        A2E["A2 规则/流程引擎<br/>合规过滤→打分→渠道→时段→话术"]
        BP["Part B 凸优化求解器<br/>SLSQP 多起点 + KKT 精修 + 上界证书"]
    end

    subgraph DATA["数据层（MySQL）"]
        ODS["ODS 原始层<br/>5 业务主表 + 相关系数"]
        DWD["DWD 明细层<br/>维度/事实表（含 CHECK 约束）"]
        DWS["DWS 汇总层<br/>dws_customer_360"]
        ADS["ADS 结果层<br/>A1全量评分 / A2候选决策 / 营销Top3<br/>组合结果 / 组合明细"]
    end

    QC["数据质量检查<br/>41 项 SQL 校验"]
    QS["质量横切"]

    APP -->|"HTTP/JSON"| SVC
    SVC -->|"PyMySQL"| DATA
    SVC -->|"调用"| ALG
    ALG -->|"读 DWD / CSV 双源"| DATA
    DATA -->|"批处理脚本 init_db"| ODS
    QC --> DATA
    ODS --> DWD --> DWS
    DWD --> ADS
```

- **算法层与数据层解耦**：算法既可从 MySQL DWD 读数据（平台模式），也可从 CSV 读数据（离线复现模式），训练与推理共用同一特征构建器，保证两种模式下特征口径一致。
- **服务层无状态**：产品/相关系数等只读数据做进程级缓存（`lru_cache`），场景配置持久化在 MySQL。

---

## 4. 数据链路一：营销响应与策略（Part A）

```mermaid
flowchart LR
    RAW["5 张业务主表<br/>t_customer / t_product / t_holding<br/>t_campaign / t_event"] -->|"init_db 批次导入"| ODS["ODS 层"]
    ODS -->|"dwd.sql 标准化"| DWD["DWD 层"]
    DWD --> F["A1 特征构建<br/>46 特征 · 严格早于目标日"]
    F --> TR["训练（时间留出后 20%）"]
    F --> INF["推理（partA_test_contacts 8000 条）"]
    TR --> M["模型工件<br/>joblib + 指标 + 系数"]
    M --> INF
    INF --> P["partA_prediction.csv<br/>contact_id, response_prob"]
    INF --> A1ADS["ads_a1_customer_product_score<br/>客户×产品概率与A1排名"]
    P -->|"response_prob 按 (customer, product) 注入"| ENG["A2 规则/流程引擎<br/>✅ 已实现"]
    DWD --> ENG
    A1ADS --> ENG
    ENG --> S["partA_strategy.csv<br/>每客户 Top3"]
    ENG --> A2ADS["ads_a2_candidate_decision<br/>ads_marketing_strategy"]
    A2ADS --> T["营销运营工作台"]
```

链路要点：

- **时间穿越防护**（三道防线）：① 持仓特征仅用 `buy_date < contact_date`；② 行为事件仅用 `event_date < contact_date`；③ 历史触达仅用 `contact_date < 当前 contact_date`；④ 训练验证按日期留出（cutoff 2026-02-01），不用随机切分。
- **A1 当前验证指标**：AUC 0.8828、F1 0.6185、Lift@10% 4.0047，三项均达到题目满分锚点。
- **A1→A2 联动**：A1 概率是唯一产品排序信号；A2 只做基础业务规则过滤、渠道/时段/话术决策与 Top3 固化。

---

## 5. 数据链路二：智能投顾组合优化（Part B）

```mermaid
flowchart LR
    P["t_product.csv（30 产品）"] --> MYSQL["MySQL<br/>dwd_dim_product<br/>ref_product_correlation"]
    C["partB_corr_matrix.csv（30×30）"] --> MYSQL
    SC["partB_scenarios.csv（20 场景）"] --> MYSQL
    MYSQL --> API["POST /portfolio/optimize<br/>（经理自定义场景）"]
    SC --> SOLVE["Part B 求解器<br/>src/algorithms/partb.py"]
    SOLVE --> STEPS["SLSQP 多起点凸优化<br/>→ min_holdings 兜底修复<br/>→ 主动集 KKT 精修<br/>→ 独立约束验证<br/>→ 切平面上界证书"]
    STEPS --> OUT["partB_allocation.csv<br/>493 行 · weight>0"]
    STEPS --> AUDIT["partB_optimality_audit.csv"]
    API --> SOLVE
```

链路要点：

- 效用函数最大化等价转化为**凸函数最小化**，约束全部线性化（流动性约束等价为"封闭产品权重 ≤ 1−min_liquid_weight"）；
- **全局最优性证书**：利用凸函数一阶切平面 + 线性规划构造效用全局上界，当前 20 个场景 optimality gap ≈ 1e-18（机器精度）；
- 提交文件落盘后**重新读回独立校验**，防止四舍五入破坏可行性；
- 当前验证：20 场景全部约束通过，落盘 total_U ≈ 0.6112。

---

## 6. 模块清单与职责边界

| 模块 | 职责 | 状态 |
|------|------|------|
| `src/partA1serving/` | 训练/推理共用的 46 特征、LR/LGBM 工件与在线推理（as-of 截断） | ✅ |
| `src/algorithms/partb.py` | Part B 凸优化求解核心 + 证书 + 独立验证（被服务层复用） | ✅ |
| `src/pipelines/solve_partB.py` | Part B CLI 入口（编排，`python -m` 执行） | ✅ |
| `src/portfolio.py` | 组合优化 API 适配（读 MySQL，参数校验）+ 场景配置 CRUD | ✅ |
| `src/customer.py` | 客户画像查询（DWS） | ✅ |
| `src/scripts/init_db.py` | 建库建表、批次导入、重建 DWD/DWS | ✅ |
| `src/sql/schema.sql` | 19 张有效表结构 + CHECK 约束 | ✅ |
| `src/sql/dwd.sql` / `src/sql/warehouse.sql` | DWD 标准化、DWS 画像 | ✅ |
| `src/sql/quality_checks.sql` | 41 项数据质量检查 | ✅ |
| `src/tests/` | 后端单元测试 | ✅ |
| `src/marketing/` | A1 排序 + A2 基础规则过滤、日批、话术与校验 | ✅ |
| `frontend/` | 今日工作台 + 官方四个核心业务页面 | ✅ |

---

## 7. 技术选型

| 层 | 选型 | 理由 |
|----|------|------|
| 语言 | Python 3.12 | 团队熟悉、算法生态完整 |
| Web 服务 | Flask 3.x | 轻量、演示可控、无重框架包袱 |
| 数据库 | MySQL 8（utf8mb4） | 分层建模（ODS/DWD/DWS/ADS）、约束与索引完整 |
| 特征/数值 | pandas + numpy | 特征工程与矩阵运算 |
| 机器学习 | LightGBM 主模型 + LR 基线 | 表格数据效果与可解释基线兼顾；版本化工件（joblib） |
| 优化 | scipy（SLSQP / linprog / root） | 凸问题精确求解 + 证书 |
| 前端 | React + Vinext | 单页工作台，四个业务页面按模块拆分 |
| 依赖管理 | uv + pyproject（提交时补 requirements.txt） | 可复现环境 |

---

## 8. 关键架构决策（ADR 摘录）

| # | 决策 | 理由 | 备选（未采用） |
|---|------|------|----------------|
| 1 | 训练/推理共用 `partA1serving` 特征装配，特征带版本号 | 口径唯一、防训练推理错配 | 两份独立特征代码（易漂移） |
| 2 | 时间留出验证（后 20% 日期） | 贴合真实预测场景，防时间泄漏 | 随机 K 折（会高估） |
| 3 | as-of 一律取**严格早于**目标日 | 题目时间穿越约束的保守实现 | 含当日（有泄漏风险） |
| 4 | 历史响应率用 Beta(2,8) 平滑 | 无历史时的中性先验 20%，避免 0/0 | 加一平滑（偏乐观） |
| 5 | Part B 用凸化 + SLSQP 多起点，而非黑盒进化算法 | 凸问题可证全局最优，配切平面上界证书 | 遗传算法（无最优性保证） |
| 6 | 算法层支持 MySQL/CSV 双数据源 | 平台模式与离线复现共用一套代码 | 只读 MySQL（答辩现场不便） |
| 7 | 业务规则进规则引擎（声明式 + 轨迹），不散落在接口 | 可审计、可解释，支撑 D 联动 | 规则散落在各 API 的 if/else |
| 8 | 模型/特征/提交文件三重自校验 | 任何格式违例 A1/A2 直接 0 分，必须前置拦截 | 人工检查 |

---

## 9. 运行视图

```mermaid
flowchart TB
    subgraph OFFLINE["离线（复现/训练）"]
        T1["python -m src.partA1serving.training.train_and_save"]
        T2["python -m src.partA1serving.training.predict"]
        T3["python -m src.marketing"]
        T4["python -m src.pipelines.solve_partB --data-dir src/data/raw"]
    end
    subgraph ONLINE["在线（平台演示）"]
        T5["python -m src.scripts.init_db"]
        T6["uv run python -m src.app"]
        T7["前端看板 → REST API"]
    end
    T1 --> M["src/partA1serving/artifacts/"]
    M --> T2
    M --> T3
    T2 --> SUB["partA_prediction.csv"]
    T3 --> SUBA2["partA_strategy.csv"]
    T4 --> SUBB["partB_allocation.csv"]
    T5 --> DB["MySQL: ODS/DWD/DWS/ADS"]
    T6 --> DB
    T7 --> T6
```

演示现场推荐顺序：`init_db.py` → 起服务 → 看板演示三条链路 → 必要时离线复跑训练/求解证明可复现。

---

## 10. 架构与评分标准映射

| 评分项 | 架构支撑 | 状态 |
|--------|----------|------|
| A1 AUC/F1/Lift | 特征工程 + 时间验证 + 模型工件 | ✅ 本地时间留出达到满分锚点，最终以隐藏标签为准 |
| A2 HitRate@3 | 同一 full A1 对 2000×30 完整评分 + 基础规则过滤 | ✅ 链路完整，最终以隐藏购买标签为准 |
| A2 格式合规 | 提交校验器（`src/marketing/validate.py`） | ✅ |
| B 效用分数 | 凸优化 + 证书 | ✅ |
| C 架构与工程 | 分层数据架构、质量检查、测试、双源算法层 | ✅ |
| C 规则/流程引擎 | `src/marketing/`（两阶段流水线 + 14 规则 + 配额） | ✅ |
| D 运营看板与联动 | 四页工作台 + 规则轨迹 + 执行归因 | ✅ |
| 加分 | 最优性证书、局部解释、版本管理、规则轨迹 | ✅ |

> 差距与分工详见 `roadmap.md`。
