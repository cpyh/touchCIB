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

## 运行环境

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（推荐的 Python 环境与依赖管理工具）
- MySQL 8（仅完整平台演示需要；离线复现三份评分 CSV 不需要）
- Node.js 22.13+（仅前端需要）

以下命令均假设当前目录为仓库根目录。推荐直接安装 Python 依赖：

```bash
uv sync
```

README 后续统一使用 `uv run python`，无需手动激活 `.venv`。如果不使用 uv，
也可以执行下面的命令；激活虚拟环境后，将后续的 `uv run python` 替换为 `python`：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

macOS 如果加载 LightGBM 时提示缺少 `libomp.dylib`，执行：

```bash
brew install libomp
```

所有随机过程固定 `random_state=42`。分析基准日为 2026-03-31；A2 的
`strategy_date` 以官方输入文件为准，为 2026-04-15。

官方输入数据已随仓库提供（`src/data/raw/`，共 9 个文件），无需手工放置：

```text
t_customer.csv  t_product.csv  t_holding.csv  t_campaign.csv  t_event.csv
partA_test_contacts.csv  partA_strategy_customers.csv
partB_scenarios.csv  partB_corr_matrix.csv
```

## 路径一：离线复现三份评分 CSV

这条路径不连接 MySQL，适合提交前复现算法结果。

### A1 营销响应预测

先训练唯一的 full LightGBM 正式模型：

```bash
uv run python -m src.partA1serving.training.train_and_save \
  --profile full --model lgbm_onehot
```

再加载这个模型生成正式预测文件：

```bash
uv run python -m src.partA1serving.training.predict \
  --model lgbm_onehot --out partA_prediction.csv
```

如需在答辩展示时间留出指标，将 `--profile full` 改为 `--profile all`，同时刷新
demo 模型。A1 使用 46 个特征，demo 时间留出验证结果为 AUC 0.8828、
F1 0.6185、Lift@10% 4.0047。所有历史特征严格使用早于 `contact_date` 的数据。

### A2 营销策略生成

```bash
uv run python -m src.marketing \
  --model lgbm_onehot \
  --output partA_strategy.csv \
  --audit-output src/data/outputs/a2_strategy_audit.csv
```

A2 不读取 `partA_prediction.csv`，而是加载与 A1/Flask 相同的 full LightGBM，
对 2000 位客户的 30 个产品×渠道进行评分，以每产品最高概率信号完成基础规则
过滤和 Top3 排序。执行渠道独立由当日日批画像策略决定：生成 Top200 经理池快照，
池外客户按画像分流至 App、电话或短信，因此渠道个性化不会改写产品 Top3。
候选网格只在日批/离线导出时计算，落 ADS 时仍聚合为每客户每产品一行。

### Part B 投资组合优化

```bash
uv run python -m src.pipelines.solve_partB \
  --data-dir src/data/raw \
  --output partB_allocation.csv \
  --audit src/data/outputs/partB_optimality_audit.csv
```

### 提交前校验

```bash
uv run python -m src.scripts.check_submission
```

校验器会检查三份正式 CSV 的列名、覆盖范围、取值边界和 Part B 全部硬约束。

## 路径二：从零初始化完整平台

### 1. 准备 MySQL 与环境变量

先确认 MySQL 8 已启动，并且所用账号具有创建数据库和数据表的权限。复制配置文件：

```bash
cp .env.example .env
```

至少检查并修改 `.env` 中的 `DB_HOST`、`DB_PORT`、`DB_USER`、`DB_PASSWORD` 和
`DB_NAME`。DeepSeek 配置是可选项；不填写密钥时，AI 摘要会自动回退为本地模板。

### 2. 初始化数仓和演示数据

```bash
uv run python -m src.scripts.init_db
uv run python -m src.scripts.run_marketing_batch --strategy-date 2026-04-15
uv run python -m src.scripts.run_portfolio_batch --calculation-date 2026-04-15
uv run python -m src.scripts.seed_demo_events --reset
```

上述过程会完成 ODS 导入、DWD/DWS 重建、A1/A2 ADS 日批、Part B ADS 日批，以及
用于执行归因演示的 30 条触达/22 条响应事件。演示事件都落在当前业务日
`2026-04-15`：在营销工作台筛选“等待回流”客户，点击“模拟系统收到新增持仓”，
系统会写入演示持仓、自动归因并把经理 KPI 从 22/30 更新为 23/30。批处理均可重复执行。

已有数据库只需补建新表或迁移字段、不希望重新导入 ODS 时，执行：

```bash
uv run python -m src.scripts.init_db --schema-only
```

### 3. 启动后端

```bash
uv run python -m src.app
```

后端默认监听 `http://127.0.0.1:5001`。健康检查：

```bash
curl http://127.0.0.1:5001/health
```

### 4. 启动前端

另开一个终端：

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

前端默认访问 `http://localhost:3000`，并通过 `VITE_API_BASE_URL` 连接 Flask。

### 平台全链路一键复现

下面的命令包含 `init_db`，因此必须先完成 MySQL 和根目录 `.env` 配置。它会依次执行：

```text
ODS/DWD/DWS → 121 个测试 → A1 full 模型与正式预测
            → A2 2000×30 评分与 Top3 → Part B → 三 CSV 红线校验
```

```bash
uv run python -m src.pipelines.run_all
uv run python -m src.pipelines.run_all --with-demo
```

`--with-demo` 会额外运行营销/组合 ADS 日批，并重置触达与响应演示事件。

## 平台数据口径

- 业务平台不读取根目录提交 CSV；营销日批从 MySQL DWD 读取全量客户和产品，
  幂等写入 `ads_a1_customer_product_score`、`ads_a2_candidate_decision` 和
  `ads_marketing_strategy`。
- 营销工作台包含互斥的“规模化触达”和“经理 VIP 通道”：前者只承载 App、
  电话和短信客户，后者从当日日批经理池快照中取未联系客户前 12 位作为今日任务；
  当天只更新执行状态和 Top12 补位，次日日批生成新快照，前一日保留为历史快照。
- 顶部全局业务日期联动客户范围、营销策略、投顾结果和经营看板；没有同日 ADS
  快照时会提示先在数据任务中心补跑，不会静默回退到其他日期。
- 数据任务中心通过 `POST /pipeline/runs` 触发受控 DAG，并通过
  `GET /pipeline/runs/latest` 展示节点状态和日志。

A1 数据库在线推理示例：

```bash
curl -X POST http://127.0.0.1:5001/marketing/response/predict \
  -H 'Content-Type: application/json' \
  -d '{"customer_id":"C000001","product_id":"P002","channel":"manager","contact_date":"2026-04-15"}'
```

## 测试

```bash
uv run python -m unittest discover -s src/tests
cd frontend && npm test
```

架构、营销规则引擎、组合优化和演示脚本见 `src/docs/`。
