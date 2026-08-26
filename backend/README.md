# 客户画像与风险评估后端

第一阶段后端使用 Flask + PyMySQL + MySQL 8.0，实现客户列表、新建客户、客户画像和画像总结。

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
```

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

## 5. 画像总结模式

默认 `AI_SUMMARY_MODE=template`，无需外部密钥即可生成本地演示总结。

需要接入远程模型时，将其改为 `remote`，并配置：

```text
AI_API_URL=兼容 Chat Completions 的完整接口地址
AI_API_KEY=密钥
AI_MODEL=模型名称
```

远程接口失败时会返回 502，但客户基础画像仍可正常查询。

## 6. 测试

测试不连接 MySQL：

```bash
python -m unittest discover backend/tests -v
```
