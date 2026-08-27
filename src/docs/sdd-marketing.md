# SDD · 营销链路（Part A）规格

> 范围：A1 营销响应预测（30 分自动）+ A2 营销策略生成（5 分自动 + Part D 验收）
> 状态：A1 ✅ ｜ A2 规则/流程引擎 ✅ 已实现（本文件为定稿 v2）
> 关联：[architecture.md](architecture.md) §4

---

## 1. A1 目标与判分口径

对 `partA_test_contacts.csv`（8000 条，列 `contact_id, customer_id, product_id, channel, contact_date`）逐条预测 `response_prob`，提交 `partA_prediction.csv`（列 `contact_id, response_prob`）。

| 指标 | 满分 | 地板 | 低锚点→分 | 高锚点→分 | 当前验证值 |
|------|------|------|-----------|-----------|------|
| AUC | 17 | 3.4 | 0.79→6.8 | 0.85→17 | **0.8828** ✅ |
| F1（3 位小数阈值扫描） | 7 | 1.4 | 0.50→2.8 | 0.615→7 | **0.6185** ✅ |
| Lift@10% | 6 | 1.2 | 2.6→2.4 | 3.3→6 | **4.0047** ✅ |

格式红线（违者 A1 记 0 分）：精确覆盖全部 contact_id、不重复不多交、概率 ∈ [0,1]、≤5 MiB。当前提交文件已通过全部自校验。

## 2. A1 特征规格（`src/partA1serving/`，schema v3）

**46 个特征 = 13 类别 + 33 数值**，训练/推理共用；模型工件的
`schema_version = 3`，并记录特征列顺序与 as-of 截止日期。

- 类别：触达渠道、产品 ID/类型/风险/流动性、6 项客户画像、2 项交叉特征，共 13 项。
- 数值：客户与产品基础数值、风险/起投/收益匹配、持仓与行为统计、历史营销平滑响应率，共 33 项。
- **as-of 三道防线**：持仓 `buy_date < contact_date`；事件 `event_date < contact_date` 且按窗口聚合；历史触达 `< 当前 contact_date`；验证按日期留出（cutoff 2026-02-01）。

## 3. A1 训练规格（`src/partA1serving/training/`）

主模型为 one-hot LightGBM，固定 `random_state=42`；demo 工件按 2026-02-01
切分训练 42642 行、验证 7358 行，full 工件使用 50000 行历史触达训练。
评估口径为 3 位小数阈值扫描 F1 与前 10% Lift。LR 工件作为可解释基线保留，
两类工件都携带模型名、特征顺序、训练范围与 as-of 元数据。

## 4. A1 推理规格（`src/partA1serving/predictor.py`）

离线 CSV 与 Flask/MySQL 在线模式共用特征服务；模型/特征版本双重校验。
正式批量入口输出 `partA_prediction.csv` 并回读自校验；在线预测返回当前
客户×产品×渠道的局部解释。业务日批的全量概率统一写入
`ads_a1_customer_product_score`。

---

## 5. A2 目标与判分口径

- 输入：`partA_strategy_customers.csv`（2000 客户，列 `customer_id, strategy_date`；**实际 strategy_date 全为 2026-04-15**，as-of 截断以此为准，非基准日 03-31）
- 输出：`partA_strategy.csv`，每客户恰好 3 行（rank=1/2/3，3 个产品不重复）
- **HitRate@3 = 命中客户数 ÷ 2000**，锚点 0.30→2 分、0.55→5 分
- 渠道/时段/话术不改变 HitRate 自动分，其个性化、合规性、平台联动由 Part D 现场验收

## 6. A2 设计哲学（v2 定稿）

**A1 管产品×渠道排序，A2 管业务可执行性。**
候选层对每个客户的 30 产品×可执行渠道调用 A1，每产品保留概率最高的
可执行渠道；A2 不再训练第二个排序模型，只执行风险、
准入、起投能力、渠道、时段和话术规则，再形成过滤后的 Top3。

## 7. 两阶段流水线（`src/marketing/pipeline.py`，✅ 已实现）

```mermaid
flowchart TB
    subgraph BATCH["阶段一：全局批次"]
        S1["生成可执行渠道集<br/>（manager 对所有客户开放）"] --> S2["30产品×可执行渠道<br/>A1评分后按产品聚合"]
        S2 --> S3["基础规则过滤<br/>（风险、准入、起投能力）"]
        S3 --> S4["客户内 Top3"]
    end
    subgraph PER["阶段二：逐客户"]
        S4 --> T1["渠道分配（rank 顺位阶梯）"] --> T2["时段推荐（职业×渠道偏好序）"]
        T2 --> T3["话术生成（模板 + 合规 + 溢出提示）"] --> T4["规则回验 → 输出"]
    end
```

- 全流程确定性执行（tie-break：product_id / customer_id 字典序），无随机数
- 每客户产出 `StrategyResult`：items（策略行）+ steps（6 步轨迹）→ `to_dict()` 供看板直用

## 8. 产品排序信号

`score(customer, product) = max A1 response_prob over executable channels`。每位客户
对 30 个产品完成聚合评分并保留原始 `a1_rank`；A2 只过滤不可执行候选，
不修改概率，避免页面出现
“队列概率”和“策略下钻概率”口径不一致。

## 9. 规则目录（`src/marketing/rules.py`，14 条，✅ 已实现）

| 类别 | rule_id | 硬/软 | 判定 |
|------|---------|-------|------|
| 合规 | `risk_match` | 硬 | 产品风险 ≤ 客户偏好；候选 <3 时自动溢出 1 级（`max_allowed_risk`） |
| 合规 | `product_launched` | 硬 | launch_date ≤ strategy_date |
| 合规 | `customer_registered` | 硬 | register_date ≤ strategy_date |
| 合规 | `aum_affordability` | 硬 | 客户 AUM ≥ 产品起投金额 |
| 记录 | `duration_valid` | 记录 | **仅留痕不拦截**：评分不校验存续期，产品池以发放 30 个为准 |
| 记录 | `min_invest_affordable` | 记录 | 仅展示用，不参与 A2 评分 |
| 渠道 | `channel_app_requires_app` | 硬 | app_push 要求 has_app=1 |
| 渠道 | `channel_call_complaint_block` | 硬 | 近 90 天投诉 ≥2 禁 call（风险规则） |
| 渠道 | `channel_manager_quota` | 兼容记录 | manager 不设全局配额，规则 ID 仅为兼容历史轨迹 |
| 渠道 | `channel_manager_eligible` | 兼容记录 | manager 不设 VIP/AUM 资格限制 |
| 时段 | `slot_in_enum` | 硬 | 5 个规定时段枚举 |
| 话术 | `script_length` | 硬 | 10 ≤ 字符数 ≤ 300 |
| 话术 | `script_compliance_note` | 硬 | 含「理财非存款，产品有风险，投资须谨慎」 |
| 话术 | `script_overshoot_warning` | 硬 | 溢出产品话术含「风险等级高于您的风险偏好，请谨慎选择」 |

### 9.1 manager 渠道（不限资格、不限配额）

- 所有客户都把 manager 纳入 A1 的产品×渠道候选空间，不再检查 VIP/AUM，也不再限制全局行数。
- `manager_quota` / `--manager-quota` 暂时保留以兼容现有接口和脚本，但不影响候选生成或最终推荐。
- manager 是否进入 Top3，由 A1 在该客户、该产品上的渠道响应概率决定。

### 9.2 渠道阶梯与时段偏好

- 可执行渠道：manager（所有客户）+ app_push（有App）+ call（无投诉限制）+ sms；每个产品保留 A1 概率最高的可执行渠道。
- 时段：职业主序 × 渠道修正拼接偏好序，55+ 前置工作日 09:00-12:00；rank1/2/3 取偏好序前 3 位
- 说明：周末/工作日响应率持平（0.188 vs 0.184），时段规则定位为业务惯例（职业作息 + 外呼合规时段），答辩不宣称数据挖掘结论

### 9.3 约束对照试算

- 正式 ADS 日批始终开启全部硬约束；试算结果只返回页面，不落库。
- 页面可单独关闭 App 安装、投诉外呼、起投能力三项约束。关闭渠道约束时，
  相应渠道会重新进入该客户 30 个产品的 A1 候选空间，再按概率重排并生成 Top3。
- 接口同时返回本次参与评分的渠道和候选数量，便于演示“进入候选空间但未进入
  Top3”与“关闭约束后渠道进入 Top3”两种结果。
- 推荐主链固定为 A1 完整候选空间、硬约束和客户内 Top3。

## 10. 话术模板（`src/marketing/templates.py`，✅ 已实现）

四渠道语态（sms 精炼 / app_push 推送 / call 顾问 / manager 贵宾专享），要素：产品名、风险等级、类型、业绩比较基准、期限（duration=0 显示"灵活存续"）、起投额、流动性；溢出产品追加风险提示；合规提示语永久保留，长度强制 ≤300（超长截断销售主体部分）。

## 11. 提交校验器（`src/marketing/validate.py`，✅ 已实现）

与题目红线逐条对应：列名/顺序、customer_id 非空、rank∈{1,2,3} 且每人恰好 3 行、产品不重复、渠道/时段枚举、话术 10–300 字符、文件 ≤10 MiB、客户精确覆盖。队友提交前可独立调用 `validate_strategy_file()`。

## 12. 复现步骤

```bash
# A1 训练与提交预测
uv run python -m src.partA1serving.training.train_and_save --profile full --model lgbm_onehot
uv run python -m src.partA1serving.training.predict --model lgbm_onehot --out partA_prediction.csv
# A2 提交文件
uv run python -m src.marketing --model lgbm_onehot --output partA_strategy.csv
# 业务 ADS 日批
uv run python -m src.scripts.run_marketing_batch --strategy-date 2026-04-15
```

A2 离线对 2000×30 组合生成 60000 条 A1 评分，再产出
`partA_strategy.csv`（6000 行）和审计文件；业务日批产出
`ads_a1_customer_product_score`、`ads_a2_candidate_decision`、
`ads_marketing_strategy`。

## 13. 当前验证结果（2026-04-15 as-of 口径）

| 检查项 | 结果 |
|--------|------|
| 行数 / 客户覆盖 | 6000 / 2000 ✅ |
| 每人 3 行、rank 1/2/3、产品不重复 | ✅ |
| 渠道/时段枚举、话术长度与合规提示 | ✅ |
| manager 资格/配额 | 无资格限制、无全局配额 ✅ |
| 无 App 客户出 app_push | 0 ✅ |
| 投诉 ≥2 客户出 call | 0 ✅ |
| 风险放宽一档补位行 | 500（严格风险且满足起投能力的候选不足 3 个时触发）✅ |
| 格式校验器 | 0 错误 ✅ |

## 14. A 链路测试

`tests/test_marketing_rules.py` 覆盖规则正反/边界，
`test_marketing_pipeline.py` 覆盖溢出补齐、配额分配、渠道禁用、A1 排序、
确定性与轨迹，`test_marketing_batch.py` 覆盖 ADS 批处理与 as-of 客户范围，
`test_marketing_validate.py` 覆盖提交红线反例。
