# GeneScope 2.0 前端更新

当前科研仪表盘与免登录版本请使用 [服务器更新说明](DASHBOARD_PUBLIC_SERVER_UPDATE.md)，包含完整上传命令、校验、自动备份、免登录网关切换和回滚。

[下载当前服务器更新包](../server_updates/GeneScope2_Dashboard_Public_20261105_v1.zip) · [SHA-256](../server_updates/GeneScope2_Dashboard_Public_20261105_v1.zip.sha256)

线上网址：[https://47.243.232.201/](https://47.243.232.201/)。应用当前组合更新包后无需网站账号密码。

通用 `update_frontend.py` 仍只更新 `frontend/dist` 和发布清单；组合包中的 `apply_server_update.py` 会在前端更新就绪后调用 `configure_public_access.py` 取消 Caddy 网站验证。旧的前端包不会自动变更网关。
