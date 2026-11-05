# GeneScope 2.0「基因猎手」服务器更新包

版本：`GeneScope2_GeneHunter_20261104_v1`，2026-11-04。

适用于已经部署 GeneScope 2.0 的服务器，沿用项目现有的 Docker Compose、HTTPS 与登录配置。此包包含整个前端的生产构建及小游戏，服务器不需要安装 Node.js 或执行 npm install。

## 上传哪些文件

将以下两个文件通过服务器 Workbench 文件管理上传到 `/root/`：

- `GeneScope2_GeneHunter_20261104_v1.zip`
- `GeneScope2_GeneHunter_20261104_v1.zip.sha256`

ZIP 内包含 `frontend/dist/`、逐文件摘要 `frontend_update.json`、更新/回滚工具 `update_frontend.py` 和本说明 `FRONTEND_UPDATE.md`。

## 1. 校验并解压

在服务器终端执行；命令用 `&&` 相连，失败时会停止后续步骤。

```bash
cd /root && \
sha256sum -c GeneScope2_GeneHunter_20261104_v1.zip.sha256 && \
mkdir /root/genescope-gene-hunter-20261104-v1 && \
python3 -m zipfile -e /root/GeneScope2_GeneHunter_20261104_v1.zip /root/genescope-gene-hunter-20261104-v1
```

若解压目录已存在，先核对是否已经解压过此版本；使用一个新的空目录，后续同步替换工具路径。不要混合解压不同更新包。

### 校验报错中出现 `$'\r'` 的处理

这表示校验文件使用了 Windows CRLF 换行，Linux 将回车符当作 ZIP 文件名的一部分。无需重新上传 ZIP，先执行下面的命令转换校验文件，然后重新执行本节的校验和解压：

```bash
cd /root && \
sed -i 's/\r$//' GeneScope2_GeneHunter_20261104_v1.zip.sha256 && \
sha256sum -c GeneScope2_GeneHunter_20261104_v1.zip.sha256
```

此操作只转换 `.sha256` 的换行，不改变 ZIP 或其摘要。本地打包工具已改为按字节写入 LF 换行，并增加对应回归测试。

## 2. 确认当前发布目录并预检

项目部署记录中的发布目录为 `/opt/genescope/releases/20261103-genescope2-v3`。若实际运行的版本目录不同，请将下方 `RELEASE` 改为当前版本目录。

```bash
RELEASE=/opt/genescope/releases/20261103-genescope2-v3
test -f "$RELEASE/genescope2_manifest.json" && \
test -f "$RELEASE/compose.genescope2.yaml" && \
docker compose -f "$RELEASE/compose.genescope2.yaml" ps && \
python3 /root/genescope-gene-hunter-20261104-v1/update_frontend.py --release "$RELEASE"
```

预期最后输出包含 `"dry_run": true`。工具会先校验原发布目录和更新文件的摘要。若出现文件校验失败，请先停止并核对当前版本，不修改摘要来跳过检查。

## 3. 应用更新并重建应用镜像

更新前等待当前训练任务结束，再在同一个终端执行：

```bash
python3 /root/genescope-gene-hunter-20261104-v1/update_frontend.py --release "$RELEASE" --apply && \
cd "$RELEASE" && \
docker compose -f compose.genescope2.yaml --progress plain build web && \
docker compose -f compose.genescope2.yaml up -d --no-build --no-deps web && \
docker compose -f compose.genescope2.yaml ps
```

请保存更新工具输出的 `backup` 路径，回滚时使用。旧前端和原发布清单会备份到发布目录旁。更新范围仅为 `frontend/dist` 及发布清单内对应摘要；持久化目录 `/opt/genescope/state-v2`、后端代码、数据、模型、证书和密码沿用原配置。容器重启时会有短暂中断，无需重新初始化数据或重新激活网关。

## 4. 检查服务和小游戏

容器启动后等待健康检查通过，再执行：

```bash
curl -fsS http://127.0.0.1:18080/api/v1/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/games/gene-hunter
```

第二条应返回 `200`。若服务未就绪，查看：

```bash
docker compose -f "$RELEASE/compose.genescope2.yaml" logs --tail=100 web
```

用原账号密码打开：

`https://47.243.232.201/games/gene-hunter`

按 `Ctrl+Shift+R` 刷新。左侧新增「学习与游戏 → 基因猎手：寻找关键特征」。确认能开始、选择基因得分、看到倒计时和本关排名，并能进入下一关。

项目现有 Nginx 配置已包含 `try_files $uri $uri/ /index.html;`，支持直接访问和刷新游戏路由。若使用自定义静态托管，同样需要 SPA 回退到 `index.html`，并保留 `/api/` 的后端代理规则。

## 回滚

将 `BACKUP` 替换为应用更新时实际输出的 `backup` 路径，等待当前训练任务结束后执行：

```bash
RELEASE=/opt/genescope/releases/20261103-genescope2-v3
BACKUP=/opt/genescope/releases/frontend-backup-实际备份目录名
python3 /root/genescope-gene-hunter-20261104-v1/update_frontend.py --release "$RELEASE" --rollback "$BACKUP" && \
cd "$RELEASE" && \
docker compose -f compose.genescope2.yaml --progress plain build web && \
docker compose -f compose.genescope2.yaml up -d --no-build --no-deps web
```

## 包验证和适用范围

- 本地生产构建、TypeScript 检查、游戏逻辑测试和实际浏览器流程已通过。
- 上传包另行验证 ZIP 校验和、逐文件摘要、资源引用以及模拟发布目录中的预检/更新/回滚。
- 本包为已有服务器的前端更新包；首次部署整套 GeneScope 需要完整后端部署包。
- 游戏使用合成教学数据，榜单为示例；个人游戏进度保存在浏览器中。
- 本地打包完成不表示服务器已更新；云端构建、健康检查和网页验收需上传后执行。

## 本地重建

在项目根目录执行，每次使用新的发布名：

```powershell
npm --prefix frontend run build
python -m cloud_deployment.build_frontend_update --name GeneScope2_GeneHunter_新的版本名 --instructions cloud_deployment/GENE_HUNTER_SERVER_UPDATE.md
```

输出目录：`cloud_deployment/dist/`。重建新版本时，请同步调整本文中的版本名和解压目录名。
