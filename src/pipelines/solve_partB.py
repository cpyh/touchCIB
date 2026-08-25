"""Part B 投资组合优化 CLI 入口。

算法核心位于 src/algorithms/partb.py（可被服务层与校验器复用），
本文件只负责命令行编排：

    python -m src.pipelines.solve_partB --data-dir src/data/raw \
        --output partB_allocation.csv \
        --audit src/data/outputs/partB_optimality_audit.csv
"""

from ..algorithms.partb import main

if __name__ == "__main__":
    raise SystemExit(main())
