# touchCIB · 智能财富管理运营平台

本仓库根目录即赛事提交包：三份正式评分 CSV、源码、前端源码、依赖文件与
复现所需的官方输入数据。所有开发代码统一放在 `src/` 内，提交时直接
改名（或压缩）整个仓库目录即可。

```text
touchCIB/                        # 提交时改名此目录
├── partA_prediction.csv         # Part A1 预测结果（contact_id, response_prob）
├── partA_strategy.csv           # Part A2 营销策略（每位目标客户 Top3）
├── partB_allocation.csv         # Part B 配置方案（scenario_id, product_id, weight）
├── src/                         # 全部开发代码
│   ├── app.py                   # Flask 服务入口
│   ├── a1_features.py           # A1 训练/推理共用 as-of 特征
│   ├── a1_inference.py          # A1 批量推理、解释与提交文件
│   ├── customer.py              # 客户画像查询
│   ├── database.py              # MySQL 连接
│   ├── portfolio.py             # 组合优化适配器
│   ├── scenario.py              # 组合优化场景配置
│   ├── marketing/               # A2 规则/流程引擎（13 规则 + 两阶段流水线 + 协同过滤）
│   ├── algorithms/              # 离线算法核心库（Part B 凸优化求解器）
│   ├── pipelines/               # CLI 批量入口（A1 训练 / Part B 求解）
│   ├── scripts/                 # 数据库初始化、提交前校验
│   ├── sql/                     # ODS/DWD/DWS/ADS 建表与质量检查 SQL
│   ├── tests/                   # 单元测试（55 个）
│   ├── data/raw/                # 官方输入数据（5 主表 + Part A/B 任务输入）
│   └── docs/                    # 架构与设计文档
├── frontend/                    # 前端源码
├── README.md                    # 本文件
└── requirements.txt             # Python 依赖列表
```

## 环境

- Python 3.12+
- MySQL 8（仅平台演示需要；离线复现三份 CSV 不依赖 MySQL）

使用 pip：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

也可以使用 uv：

```bash
uv sync
```

所有随机过程固定 `random_state=42`。分析基准日 2026-03-31（A2 的
`strategy_date` 以官方输入文件为准，为 2026-04-15）。

**数据准备**：官方输入数据已随仓库提供（`src/data/raw/`，共 9 个文件），
clone 后即可复现，无需手工放置：

```text
t_customer.csv  t_product.csv  t_holding.csv  t_campaign.csv  t_event.csv
partA_test_contacts.csv  partA_strategy_customers.csv
partB_scenarios.csv  partB_corr_matrix.csv
```

## 复现 A1 营销响应预测

训练 Logistic Regression 基线并执行时间留出验证（cutoff 2026-01-14）：

```bash
python -m src.pipelines.train_a1_baseline
```

使用 CSV 数据源推理并重新生成正式文件：

```bash
python -m src.a1_inference \
  --source csv \
  --output partA_prediction.csv \
  --audit-output src/data/outputs/a1_prediction_audit.csv
```

A1 特征严格使用早于对应 `contact_date` 的持仓、行为和历史触达数据
（不含同日）。

## 复现 A2 营销策略生成

```bash
python -m src.marketing \
  --predictions partA_prediction.csv \
  --output partA_strategy.csv \
  --audit-output src/data/outputs/a2_strategy_audit.csv \
  --cf-audit src/data/outputs/a2_cf_similarity.csv
```

规则/流程引擎（`src/marketing/`）为每位目标客户生成 Top3 产品、渠道、
时段与话术：产品排序 = A1 概率 + 持有产品协同过滤相似度（模型管产品），
合规/渠道/时段/话术由 13 条规则决定（规则管其余），manager 渠道按
资格 + 全局配额分配（默认 600 行）。行为和持仓严格按 `strategy_date`
截断，落盘后自动执行与题目红线一致的格式校验。

## 复现 Part B 投资组合优化

```bash
python -m src.pipelines.solve_partB \
  --data-dir src/data/raw \
  --output partB_allocation.csv \
  --audit src/data/outputs/partB_optimality_audit.csv
```

求解器（凸化 + SLSQP 多起点 + KKT 精修 + 切平面上界证书）在写出后
重新读取正式 CSV，校验 20 个场景的全部硬约束，并输出最优性审计。

## 提交前校验

一键校验三份正式 CSV 与题目红线的一致性：

```bash
python -m src.scripts.check_submission
```

## 平台演示

复制环境变量并初始化 MySQL（建表 + 导入 ODS + 重建 DWD/DWS）：

```bash
cp .env.example .env
python -m src.scripts.init_db
python -m src.a1_inference --source mysql --persist-db \
  --output partA_prediction.csv
python -m src.app
```

服务默认监听 `http://127.0.0.1:5001`，健康检查：

```bash
curl http://127.0.0.1:5001/health
```

## 测试

```bash
python -m unittest discover -s src/tests
```

架构、营销规则引擎与组合优化设计见 `src/docs/`。
