# 智能财富管理运营平台前端

赛事演示前端，通过 Flask HTTP API 展示四个业务模块：

- 客户360：DWS画像、风险与营销证据；
- Part B智能投顾：官方场景、实时组合优化与约束检查；
- Part A营销运营：A1概率、A2 Top3、规则轨迹与响应归因；
- Part C/D看板：算法指标、数据分层、提交产物和运营漏斗。

前端不直连MySQL，也不使用D1存储业务数据。

## 启动

先在仓库根目录启动Flask服务：

```bash
uv run python -m src.app
```

再启动前端：

```bash
cd frontend
npm install
npm run dev
```

默认访问 `http://localhost:3000`，后端默认地址为
`http://127.0.0.1:5001`。如需修改，可设置
`VITE_API_BASE_URL`。

## 目录

```text
frontend/
├── app/
│   ├── page.tsx          # 侧边栏和四个模块切换
│   ├── layout.tsx
│   └── globals.css
├── modules/
│   ├── customer.tsx      # 客户360
│   ├── portfolio.tsx     # Part B智能投顾
│   ├── marketing.tsx     # Part A营销运营
│   └── dashboard.tsx     # Part C/D看板
└── shared/
    ├── api.ts            # Flask请求函数
    └── ui.tsx            # 少量公共展示组件
```

每个业务模块只有一个TSX和一个CSS文件，便于多人按模块协作。

## 验证

```bash
npm test
```

该命令会先完成生产构建，再执行首页渲染检查。
