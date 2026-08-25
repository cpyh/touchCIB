# 五人协作目录约定

**本仓库根目录即赛事提交包**（提交时直接改名/压缩整个仓库），
所有开发代码统一放在 `src/` 内。不再使用 `submission/` 组装副本，
根目录三份正式 CSV 就是最终提交物。

| 角色 | 主维护范围 | 交付契约 |
|------|------------|----------|
| A1 算法 | `src/a1_features.py`、`src/a1_inference.py`、`src/pipelines/train_a1_baseline.py` | `contact_id,response_prob` |
| A2 算法 | `src/marketing/` | 每客户 Top3 策略与规则轨迹 |
| Part B 算法 | `src/algorithms/partb.py`、`src/pipelines/solve_partB.py`、`src/portfolio.py` | `scenario_id,product_id,weight` |
| 数据/后端集成 | `src/sql/`、`src/scripts/`、`src/app.py`、数据库访问模块 | DWD/DWS/ADS 与 HTTP API |
| 前端 | `frontend/` | 只通过 Flask API 消费数据 |

以下共享文件由数据/后端集成人统一合并：

- `README.md`
- `requirements.txt`
- `pyproject.toml` / `uv.lock`
- `src/app.py`
- `.env.example`
- 根目录三份正式 CSV（`partA_prediction.csv` / `partA_strategy.csv` / `partB_allocation.csv`）

协作规则：

1. `src/data/raw/` 是官方输入，只读，不提交人工改写版本。
2. `src/data/outputs/` 是可重建产物，不作为成员之间的代码接口。
3. 跨模块使用文档和数据结构约定，不直接复制另一成员的实现。
4. 三份正式 CSV 只能由各自流水线生成，禁止手工编辑。
5. 提交前由集成人运行 `python -m src.scripts.check_submission` 一键校验三份 CSV。
