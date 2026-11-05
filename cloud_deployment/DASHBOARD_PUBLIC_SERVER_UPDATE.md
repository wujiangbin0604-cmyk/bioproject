# GeneScope 2.0 科研仪表盘更新包（免登录）

线上网址：**[https://47.243.232.201/](https://47.243.232.201/)**。

本包 `GeneScope2_Dashboard_Public_20261105_v1.zip` 包含完整编译前端、更新校验工具和取消 Caddy 网站账号密码验证的工具。应用成功后首页、科研模块和基因猎手无需网站账号密码。此处取消的是网页验证，服务器 Workbench / SSH 登录仍按原方式使用。

适用现有发布目录 `/opt/genescope/releases/20261103-genescope2-v3` 与网关目录 `/opt/genescope/gateway/20261102-ip-https`。保留 HTTPS、证书卷、Origin 与请求限制、训练资源限制、数据和模型。更新包不携带密码、SSH 密钥、原始矩阵或模型。

## 上传后执行

把 ZIP 与同名 `.zip.sha256` 上传到服务器 `/root`。等待正在运行的实验结束，在 Workbench 终端执行下面整段命令：

```bash
set -eu
cd /root
sha256sum -c GeneScope2_Dashboard_Public_20261105_v1.zip.sha256
mkdir /root/genescope-dashboard-public-20261105-v1
python3 -m zipfile -e /root/GeneScope2_Dashboard_Public_20261105_v1.zip /root/genescope-dashboard-public-20261105-v1
python3 /root/genescope-dashboard-public-20261105-v1/apply_server_update.py \
  --release /opt/genescope/releases/20261103-genescope2-v3 \
  --gateway-dir /opt/genescope/gateway/20261102-ip-https \
  --apply
```

每条命令失败即停止。该目录如已存在，不要覆盖，先查看上次执行记录；可使用已解压目录重新执行最后一条命令。实际部署目录不同则修改两个路径，不要猜测或删除现有目录。

更新器会依次：校验更新工具与现有全部发布文件 → 拒绝中断正在运行的实验 → 校验免登录 Caddy 候选配置 → 备份并替换前端 → 构建 / 启动应用容器 → 等待 API 就绪 → 备份并取消网关的 `basic_auth` → 重建网关 → 通过本机 HTTPS 不带账号密码访问首页。

不需要在服务器安装 Node.js。操作会短暂重启应用与网关，持久化目录 `/opt/genescope/state-v2` 保留。若切换失败，网关恢复原配置，组合更新器恢复原前端并尝试恢复旧服务；恢复容器失败会明确输出备份路径及错误。

默认不传 `--apply` 只做校验，不替换前端或切换网关。

## 验收

```bash
curl -fsS http://127.0.0.1:18080/api/v1/health
curl --noproxy '*' --connect-to 47.243.232.201:443:127.0.0.1:443 \
  -sS -o /dev/null -w '%{http_code}\n' https://47.243.232.201/
curl --noproxy '*' --connect-to 47.243.232.201:443:127.0.0.1:443 \
  -sS -o /dev/null -w '%{http_code}\n' https://47.243.232.201/games/gene-hunter
```

公网两项预期均为 `200`，不使用 `-u`、账号密码或 `-k`。浏览器使用无痕窗口打开线上网址并按 `Ctrl+Shift+R`，确认没有登录弹窗、首页是新仪表盘、“开始挑战”可进入小游戏、数据集切换刷新图表。

## 分别更新或回滚

仅取消网站验证（前端已更新时）：

```bash
python3 /root/genescope-dashboard-public-20261105-v1/configure_public_access.py apply
```

恢复原网关配置（包括原网站验证）：

```bash
python3 /root/genescope-dashboard-public-20261105-v1/configure_public_access.py rollback
```

回滚前端，使用更新输出中真实的 `backup` 路径：

```bash
python3 /root/genescope-dashboard-public-20261105-v1/update_frontend.py \
  --release /opt/genescope/releases/20261103-genescope2-v3 \
  --rollback /opt/genescope/releases/frontend-backup-实际输出路径
cd /opt/genescope/releases/20261103-genescope2-v3
docker compose -f compose.genescope2.yaml build web && \
docker compose -f compose.genescope2.yaml up -d --no-deps --no-build web
```

## 从源码重建

```powershell
npm --prefix frontend run build
python -m cloud_deployment.build_frontend_update --name GeneScope2_Dashboard_Public_新的版本名 --instructions cloud_deployment/DASHBOARD_PUBLIC_SERVER_UPDATE.md --public-access
```

输出 ZIP 与 SHA-256 到 `cloud_deployment/dist`，不会覆盖同名包。GitHub 代码与本地更新包准备完成不代表已上线；只有服务器执行应用命令并通过免登录 HTTPS 验收后，线上更新才完成。

认证配置依据：[Caddy basic_auth 官方文档](https://caddyserver.com/docs/caddyfile/directives/basic_auth)。
