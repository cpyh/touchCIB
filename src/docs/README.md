# touchCIB 设计文档索引

> 本文档集用于团队内部对齐与答辩准备。**只包含设计文档，不含代码。**
> 状态图例：✅ 已实现并验证 ｜ 🟡 设计已定、待实现 ｜ ⬜ 待设计

## 文档导航

| 文档 | 内容 | 用途 |
|------|------|------|
| [architecture.md](architecture.md) | 系统整体架构设计：分层、两条数据链路、模块边界、技术选型、关键架构决策 | 评审架构、答辩架构页、队友对齐总蓝图 |
| [sdd-marketing.md](sdd-marketing.md) | A 链路规格：A1 特征/训练/推理、A2 策略契约、规则/流程引擎设计 | A1/A2 实现与接口对齐的依据 |
| [sdd-portfolio.md](sdd-portfolio.md) | B 链路规格：Part B 优化求解、约束校验、提交文件口径 | Part B 复现与答辩解释 |
| [sdd-platform.md](sdd-platform.md) | C/D 平台规格：数据分层、API、前端看板交互草案 | 平台工程实现与明天前端讨论的底稿 |
| [presentation.md](presentation.md) | 答辩 PPT 大纲、每页要点、演示脚本、追问预案 | 答辩材料 |
| [roadmap.md](roadmap.md) | 与评分标准的差距清单、分工建议、里程碑 | 排期与分工 |

## 建议阅读顺序

1. 先读 `architecture.md` 建立全局视图（15 分钟）
2. 按自己负责的链路读对应 SDD：
   - 负责 A1/A2 的队友 → `sdd-marketing.md`
   - 负责 Part B / 平台 → `sdd-portfolio.md`、`sdd-platform.md`
3. 沟通分工与排期用 `roadmap.md`
4. 答辩准备用 `presentation.md`

## 全局约定

- 分析基准日：**2026-03-31**；所有随机过程 `random_state=42`
- **时间穿越约束**：任何特征构造不得使用目标日期（`contact_date` / `strategy_date`）当天及之后的数据，一律取严格早于目标日期的数据（`<`，不含同日）
- 提交文件列名与枚举以题目原文为准，代码与文档共用同一套常量定义
- 状态标记中"已实现"以仓库当前代码与根目录三份正式 CSV 产出为准
