"""partA1serving 的自包含配置：路径解析 + 题面相关常量。

与全局 spec.py 的关系
---------------------
`spec.py` 是"提交格式 + 校验器 + Part B"的唯一事实来源，仍留在 `submission/src/`。
本模块是 A1 服务包的自包含配置，**不 import spec**，使 partA1serving 目录可整体
拷走独立部署（models 产物随包内置，数据路径通过环境变量注入）。

为避免两处常量漂移，`tests/test_bootstrap.py` 有断言校验
config 的 RANDOM_STATE / VALID_CHANNELS / SUBMISSION_DIR / FILE_PREDICTION / MIB
与 spec 中的对应值完全一致。

路径优先级：显式参数 > 环境变量 > 默认推导。

环境变量清单
------------
    WMP_PKG_DIR                 数据包根目录（data/ 的上级）
    WMP_DATA_DIR                直接指定 data/，优先于 WMP_PKG_DIR 推导
    WMP_MODELS_DIR              模型产物根目录（默认随包内置的 artifacts/）
    WMP_TEST_CONTACTS_CSV       partA_test_contacts.csv（仅离线打分需要）
    WMP_STRATEGY_CUSTOMERS_CSV  partA_strategy_customers.csv（仅 A2 需要）
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------- 默认目录层级
# 本文件位于 <pkg>/submission/src/partA1serving/config.py
_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))  # .../partA1serving
_SRC_DIR = os.path.dirname(_PACKAGE_DIR)  # partA1serving 的父目录
SUBMISSION_DIR = os.path.dirname(_SRC_DIR)  # 原仓库：.../submission
_DEFAULT_PKG_DIR = os.path.dirname(SUBMISSION_DIR)  # 原仓库：<pkg>


def _default_pkg_dir() -> str:
    """数据根目录的默认推导（兼容两种布局）。

    - 自包含部署：data 与 partA1serving 包**同级**（同在一个目录下），
      此时包的父目录即数据根目录；
    - 原仓库：包位于 <pkg>/submission/src/ 下，data 在 <pkg>/data，
      故回退到往上三级。

    判据是"父目录下是否存在 data 目录"：存在则认为是自包含部署。
    无论哪种情况，仍可被显式参数 / 环境变量覆盖（见 configure_paths）。
    """
    if os.path.isdir(os.path.join(_SRC_DIR, "data")):
        return _SRC_DIR
    return _DEFAULT_PKG_DIR

# ---------------------------------------------------------------- 环境变量
ENV_PKG_DIR = "WMP_PKG_DIR"
ENV_DATA_DIR = "WMP_DATA_DIR"
ENV_MODELS_DIR = "WMP_MODELS_DIR"
ENV_TEST_CONTACTS = "WMP_TEST_CONTACTS_CSV"
ENV_STRATEGY_CUSTOMERS = "WMP_STRATEGY_CUSTOMERS_CSV"

ENV_VARS = (
    ENV_PKG_DIR,
    ENV_DATA_DIR,
    ENV_MODELS_DIR,
    ENV_TEST_CONTACTS,
    ENV_STRATEGY_CUSTOMERS,
)

# 在线服务启动时必须能读到的参考数据（缺任一张则历史特征无法装配）
SERVING_DATA_FILES = (
    "t_customer.csv",
    "t_product.csv",
    "t_campaign.csv",
    "t_holding.csv",
    "t_event.csv",
)


def _default_data_dir(pkg_dir: str) -> str:
    """data 目录的默认推导（兼容原始 CSV 是否下沉到 raw/ 子目录）。

    - 本仓库：原始 CSV 放在 data/raw/ 下；
    - 自包含部署：CSV 直接平铺在 data/ 下。

    判据是"哪一层能看到 t_customer.csv"，看不到则退回 data/ 本身，
    让 bootstrap.verify() 报出缺失路径而非静默指向错误目录。
    """
    base = os.path.join(pkg_dir, "data")
    raw = os.path.join(base, "raw")
    if os.path.exists(os.path.join(raw, SERVING_DATA_FILES[0])):
        return raw
    return base

# ---------------------------------------------------------------- 常量（须与 spec.py 一致）
RANDOM_STATE = 42
VALID_CHANNELS = ("sms", "call", "app_push", "manager")
FILE_PREDICTION = "partA_prediction.csv"
MIB = 1024 * 1024

# ---------------------------------------------------------------- 路径（由 configure_paths 赋值）
# 声明后由 configure_paths() 赋初值，保证类型检查器视其为 str
PKG_DIR: str = ""
DATA_DIR: str = ""
MODELS_DIR: str = ""
TEST_CONTACTS_CSV: str = ""
STRATEGY_CUSTOMERS_CSV: str = ""
PRODUCT_CSV: str = ""


def _env_path(name: str) -> str | None:
    """读环境变量并规范化为绝对路径。空串视为未设置。"""
    raw = os.environ.get(name, "").strip()
    return os.path.abspath(os.path.expanduser(raw)) if raw else None


def configure_paths(
    pkg_dir: str | None = None,
    data_dir: str | None = None,
    models_dir: str | None = None,
    test_contacts_csv: str | None = None,
    strategy_customers_csv: str | None = None,
) -> None:
    """(重新)解析全部路径常量。

    各调用方一律通过 `config.XXX` 属性访问（而非 `from config import XXX`），
    因此此处更新模块全局后，对已导入的模块同样立即生效。
    """
    global PKG_DIR, DATA_DIR, MODELS_DIR
    global TEST_CONTACTS_CSV, STRATEGY_CUSTOMERS_CSV, PRODUCT_CSV

    def _pick(explicit: str | None, env_name: str, fallback: str) -> str:
        if explicit:
            return os.path.abspath(os.path.expanduser(explicit))
        return _env_path(env_name) or fallback

    PKG_DIR = _pick(pkg_dir, ENV_PKG_DIR, _default_pkg_dir())
    DATA_DIR = _pick(data_dir, ENV_DATA_DIR, _default_data_dir(PKG_DIR))
    # 模型产物默认随包内置；部署时可用 WMP_MODELS_DIR 指向外部卷
    MODELS_DIR = _pick(models_dir, ENV_MODELS_DIR, os.path.join(_PACKAGE_DIR, "artifacts"))

    def _side_car(name: str) -> str:
        """题面附带的 CSV：优先取 data 目录，其次退回数据根目录。"""
        in_data = os.path.join(DATA_DIR, name)
        return in_data if os.path.exists(in_data) else os.path.join(PKG_DIR, name)

    TEST_CONTACTS_CSV = _pick(
        test_contacts_csv, ENV_TEST_CONTACTS, _side_car("partA_test_contacts.csv")
    )
    STRATEGY_CUSTOMERS_CSV = _pick(
        strategy_customers_csv,
        ENV_STRATEGY_CUSTOMERS,
        _side_car("partA_strategy_customers.csv"),
    )
    PRODUCT_CSV = os.path.join(DATA_DIR, "t_product.csv")


def current_paths() -> dict[str, str]:
    """当前生效的路径快照，供自检与日志打印。"""
    return {
        "PKG_DIR": PKG_DIR,
        "DATA_DIR": DATA_DIR,
        "MODELS_DIR": MODELS_DIR,
        "SUBMISSION_DIR": SUBMISSION_DIR,
        "TEST_CONTACTS_CSV": TEST_CONTACTS_CSV,
        "STRATEGY_CUSTOMERS_CSV": STRATEGY_CUSTOMERS_CSV,
    }


# 导入时按默认规则解析一次（含环境变量），使既有调用方无需改动
configure_paths()
