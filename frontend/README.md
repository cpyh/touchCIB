# touchCIB frontend

前端成员在此目录维护运营工作台源码。本仓库根目录即赛事提交包，
本目录随包直接提交，无需额外打包步骤。

前端只通过 Flask HTTP API 获取数据，不直接连接 MySQL，也不读取
`src/data/raw/` 中的比赛文件。
