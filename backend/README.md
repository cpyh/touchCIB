# 智能财富管理运营平台后端

后端使用 Flask + PyMySQL + MySQL 8.0。当前已实现客户画像与风险评估模块，以及可视化看板中基于现有四张业务表的汇总功能。

## 目录

```text
backend/
├── app/
│   ├── routes/       # HTTP 接口
│   ├── services/     # 客户、画像和总结业务逻辑
│   ├── config.py     # 环境配置
│   ├── db.py         # MySQL 连接
│   ├── risk.py       # 新建客户简易风险规则
│   └── validation.py # 请求校验
├── scripts/          # 建库与 CSV 导入
├── sql/schema.sql    # MySQL 建表脚本
├── tests/            # 自动化测试
└── run.py            # 启动入口
```

## 1. 安装依赖

在 `touchCIB` 根目录执行：

```bash
uv sync
```

如果不使用 uv：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. 配置 MySQL

```bash
cp .env.example .env
```

按本机 MySQL 修改 `.env` 中的 `DB_USER` 和 `DB_PASSWORD`。默认数据库名为 `touch_cib`。

初始化数据库和四张表：

```bash
python -m backend.scripts.init_db
```

导入项目 `src/data/raw` 下的四个 CSV：

```bash
python -m backend.scripts.import_data
```

导入脚本可以重复运行，相同主键的数据会更新，不会重复插入。

## 3. 启动服务

```bash
python -m backend.run
```

默认地址：`http://127.0.0.1:8000`。

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

## 4. 接口

```text
GET  /api/v1/customers
POST /api/v1/customers
GET  /api/v1/customers/{customer_id}/profile
POST /api/v1/customers/{customer_id}/ai-summary
GET  /api/v1/dashboard/overview
GET  /api/v1/dashboard/portfolio?scenario_id=S01
```

看板总览目前返回真实的客户数、AUM、产品数、持仓金额、客户风险分布和产品类型持仓分布。A1、A2、Part B 和营销漏斗尚未接入的部分返回 `status: NOT_READY` 及空值，不使用模拟业务结果。

新建客户示例：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/customers \
  -H 'Content-Type: application/json' \
  -d '{
    "age_group": "35-44",
    "city": "上海",
    "occupation": "企业职员",
    "income_level": "30-50万",
    "register_date": "2026-08-26",
    "aum": 650000,
    "vip_level": "金卡",
    "has_app": true
  }'
```

## 5. DeepSeek 画像总结

画像总结会真实调用 DeepSeek Chat Completions。请在 `.env` 中配置：

```text
DEEPSEEK_API_KEY=你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_TIMEOUT_SECONDS=60
```

后端通过 OpenAI Python SDK 的兼容客户端调用 DeepSeek，并启用 thinking、`reasoning_effort=high`、JSON Output 和非流式响应。返回内容拆分为画像概述、需求洞察、服务建议和高亮关键词；未配置密钥或调用失败时返回 502，但客户基础画像仍可正常查询。

## 6. 测试

测试不连接 MySQL：

```bash
python -m unittest discover backend/tests -v
```
