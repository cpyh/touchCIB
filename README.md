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
│   ├── partA1serving/           # A1特征、LR/LGBM训练、模型工件与在线推理
│   ├── customer.py              # 客户画像查询
│   ├── database.py              # MySQL 连接
│   ├── portfolio.py             # 组合优化适配器（在线优化 + 场景配置存取）
│   ├── marketing/               # A1排名 + A2基础规则过滤 + ADS日批
│   ├── algorithms/              # 离线算法核心库（Part B 凸优化求解器）
│   ├── pipelines/               # CLI 批量入口（run_all 一键编排 / A1 训练 / Part B 求解）
│   ├── scripts/                 # 数据库初始化、提交前校验
│   ├── sql/                     # ODS/DWD/DWS/ADS 建表与质量检查 SQL
│   ├── tests/                   # 单元测试（持续随功能补充）
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

训练队友提供的 demo/full 两套 LightGBM 模型；demo 用于时间留出验证，full
使用全部历史训练数据：

```bash
python -m src.partA1serving.training.train_and_save \
  --profile all --model lgbm_onehot
```

使用同一套特征工程重新训练全量模型并生成正式文件：

```bash
python -m src.partA1serving.training.predict \
  --model lgbm_onehot --out partA_prediction.csv
```

A1 特征严格使用早于对应 `contact_date` 的持仓、行为和历史触达数据
（不含同日）。离线训练读取官方 CSV；Flask 在线预测读取 MySQL DWD，二者
共享同一特征装配与历史索引，避免训练/服务口径漂移。
当前提交模型使用 46 个特征；demo 时间留出验证结果为 AUC 0.8828、
F1 0.6185、Lift@10% 4.0047，三项均达到题目满分锚点。

## 复现 A2 营销策略生成

业务平台不读取提交 CSV。批处理从 MySQL DWD 读取全量客户与
产品，先生成 A1 客户×产品概率排名，再按风险、准入、起投能力、
渠道、时段和话术规则过滤，幂等写入三张 ADS 表：

```bash
python -m src.scripts.run_marketing_batch --strategy-date 2026-04-15
```

可视化看板内的“数据任务中心”提供手动补跑演示：

```text
ODS/DWD/DWS 刷新 → 41 项质量门禁 → 营销 ADS → 投顾 ADS → BI 就绪
```

页面选择业务日期后，通过 `POST /pipeline/runs` 启动固定白名单任务，并轮询
`GET /pipeline/runs/latest` 展示 DAG 节点状态和实时日志。该链路不会
覆盖根目录的正式评分 CSV，也不会重置营销演示事件。

```json
{"business_date": "2026-04-15"}
```

业务日期用于营销与组合优化 ADS 批次，可幂等补跑任意历史日期；
`dws_customer_360` 仍保持赛事基准画像快照日 `2026-03-31`。经营看板
默认查询数据库中的最新 ADS 批次，因此补跑更早日期不会覆盖更新日期的展示。

赛事自动评分所需的 `partA_strategy.csv` 是独立的离线导出物，仅在
提交流程中生成：

```bash
python -m src.marketing \
  --predictions partA_prediction.csv \
  --output partA_strategy.csv \
  --audit-output src/data/outputs/a2_strategy_audit.csv
```

A2 的职责是在 A1 概率顺序上做基础业务规则过滤并取 Top3。每条候选的通过/过滤原因、
模型版本、特征日期和批次号均落库，供策略下钻审计。

## 复现 Part B 投资组合优化

```bash
python -m src.pipelines.solve_partB \
  --data-dir src/data/raw \
  --output partB_allocation.csv \
  --audit src/data/outputs/partB_optimality_audit.csv
```

求解器（凸化 + SLSQP 多起点 + KKT 精修 + 切平面上界证书）在写出后
重新读取正式 CSV，校验 20 个场景的全部硬约束，并输出最优性审计。

## 一键复现（run_all）

进数 → 质量门禁（当前 105 个单元测试）→ A1 → A2 → Part B → 三 CSV 红线校验，
任何一步失败立即中止：

```bash
python -m src.pipelines.run_all                # A1 默认使用LGBM重训
python -m src.pipelines.run_all --with-demo    # 追加：ADS日批 + 演示事件预置
```

## 提交前校验

单跑三份正式 CSV 的红线校验：

```bash
python -m src.scripts.check_submission
```

## 平台演示

复制环境变量并初始化 MySQL（建表 + 导入 ODS + 重建 DWD/DWS）：

```bash
cp .env.example .env
python -m src.scripts.init_db
python -m src.scripts.run_marketing_batch --strategy-date 2026-04-15
python -m src.scripts.run_portfolio_batch --calculation-date 2026-04-15
python -m src.scripts.seed_demo_events --reset    # 演示事件：30 触达 / 22 响应
python -m src.app
```

服务默认监听 `http://127.0.0.1:5001`，健康检查：

```bash
curl http://127.0.0.1:5001/health
```

已有数据库升级代码后只需补建新表与幂等约束，不会重导ODS：

```bash
python -m src.scripts.init_db --schema-only
```

营销工作台以8000位客户为全量机会池，按最新 `ads_a1_customer_product_score`
中的客户最高机会分排序。Top3、规则轨迹与执行参数统一读取
`ads_marketing_strategy`；请求阶段不会读 CSV、不会调用遗留 A2 模型，
也不会临时生成并冻结策略。

A1数据库在线推理：

```bash
curl -X POST http://127.0.0.1:5001/marketing/response/predict \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"C000001","product_id":"P002","channel":"manager","contact_date":"2026-04-15"}'
```

前端（Next.js，开发端口 3000）：

```bash
cd frontend && npm install && npm run dev
```

演示动作（docs/demo-design.md §5.2）：
改参数重算（Tab2/Tab3）、标记已触达/已响应看状态与 KPI 变化
（经理转化 22/30 → 23/30）、Tab3 切换历史回放日期看日批排名变动。

## 测试

```bash
python -m unittest discover -s src/tests
```

架构、营销规则引擎与组合优化设计见 `src/docs/`。
