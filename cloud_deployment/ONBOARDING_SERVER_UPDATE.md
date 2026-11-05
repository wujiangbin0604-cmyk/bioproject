# GeneScope 2.0 首页引导与基因猎手更新

发布名：`GeneScope2_Onboarding_20261104_v1`。适用于现有 GeneScope 2.0 服务器，包含此前基因猎手及本次首页流程模块，可直接从尚未安装小游戏的旧前端升级。

## 更新内容

- 首页欢迎区下方新增「一、推荐的用户进入流程」：四个纵向步骤、重点欢迎卡片、向下箭头及响应式布局。
- 首次访问自动显示一次欢迎引导，支持手动重开、键盘操作和减少动态效果。
- 从首页流程或弹窗进入基因猎手及数据集中心。
- 包含完整基因猎手五关、计分、Combo、结算与本地成长记录。

此包为已编译前端，服务器无需安装 Node.js。更新工具备份旧前端，修改 `frontend/dist` 与发布清单对应条目；沿用现有后端、数据、模型、Compose、证书和登录配置。

## 1. 上传

将下面两个文件通过 Workbench 上传到服务器 `/root/`：

```text
GeneScope2_Onboarding_20261104_v1.zip
GeneScope2_Onboarding_20261104_v1.zip.sha256
```

本次校验文件使用 Linux LF 换行，已修正此前文件名末尾出现 `$'\r'` 的问题。如果上传工具改变了换行，可先执行 `sed -i 's/\r$//' /root/GeneScope2_Onboarding_20261104_v1.zip.sha256`，然后重新校验。

## 2. 校验并解压到新目录

在服务器终端执行：

```bash
cd /root && \
sha256sum -c GeneScope2_Onboarding_20261104_v1.zip.sha256 && \
mkdir /root/genescope-onboarding-20261104-v1 && \
python3 -m zipfile -e /root/GeneScope2_Onboarding_20261104_v1.zip /root/genescope-onboarding-20261104-v1
```

应该看到 `GeneScope2_Onboarding_20261104_v1.zip: OK`。若解压目录已存在，请核对是否已解压本包；不要向其他版本目录混合解压。每组命令中 `&&` 前的步骤失败时不会继续后面的步骤。

## 3. 检查发布目录和更新包

项目记录的当前部署目录如下；如实际目录不同，仅修改 `RELEASE` 后再执行：

```bash
RELEASE=/opt/genescope/releases/20261103-genescope2-v3
test -f "$RELEASE/genescope2_manifest.json" && \
test -f "$RELEASE/compose.genescope2.yaml" && \
docker compose -f "$RELEASE/compose.genescope2.yaml" ps && \
python3 /root/genescope-onboarding-20261104-v1/update_frontend.py --release "$RELEASE"
```

预期输出包含 `"dry_run": true`。这一步只校验，不替换文件。无论此前是否安装过基因猎手更新，工具都会依据当前发布清单核对现有文件；摘要不符时停止，不修改清单来跳过检查。

## 4. 应用更新并重建启动

等待当前训练任务结束后，在同一个终端执行：

```bash
python3 /root/genescope-onboarding-20261104-v1/update_frontend.py --release "$RELEASE" --apply && \
cd "$RELEASE" && \
docker compose -f compose.genescope2.yaml --progress plain build web && \
docker compose -f compose.genescope2.yaml up -d --no-build --no-deps web && \
docker compose -f compose.genescope2.yaml ps
```

请保存更新工具输出的 `backup` 路径，回滚时使用。无需重新初始化数据或切换 HTTPS 网关。应用容器重启期间会有短暂中断。

## 5. 服务和页面验收

容器启动后等待健康检查通过，再执行：

```bash
curl -fsS http://127.0.0.1:18080/api/v1/health
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18080/games/gene-hunter
```

后两条应返回 `200`。静态路由返回 200 只表示服务器可访问，仍需在浏览器检查页面：

1. 打开 `https://47.243.232.201/`，使用原账号登录并按 `Ctrl+Shift+R` 刷新。
2. 确认欢迎区下方出现「一、推荐的用户进入流程」四步模块。
3. 确认“了解欢迎引导设计”能打开弹窗，关闭后可再次打开。
4. 首次访问自动显示一次；同一浏览器已确认过引导时不会自动重复显示。
5. 确认第三步和弹窗按钮能进入 `/games/gene-hunter`，游戏可开始并得分；第四步进入数据集中心。
6. 检查原有数据集、实验和模型仍能正常访问。

个人欢迎引导记录按网站来源保存在浏览器中，本地预览和服务器网站分别记录。游戏数据为合成教学示例，排行榜为示例。

如服务尚未就绪，查看日志：

```bash
docker compose -f "$RELEASE/compose.genescope2.yaml" logs --tail=100 web
```

现有 Nginx 已配置 SPA 路由回退，首页与游戏路由无需额外修改网关。

## 回滚

先将 `BACKUP` 改为更新工具实际输出的路径，等待当前训练任务结束，再执行：

```bash
RELEASE=/opt/genescope/releases/20261103-genescope2-v3
BACKUP=/opt/genescope/releases/frontend-backup-实际备份目录名
python3 /root/genescope-onboarding-20261104-v1/update_frontend.py --release "$RELEASE" --rollback "$BACKUP" && \
cd "$RELEASE" && \
docker compose -f compose.genescope2.yaml --progress plain build web && \
docker compose -f compose.genescope2.yaml up -d --no-build --no-deps web
```

## 本地验证范围

生产构建与 TypeScript 检查已通过。实际浏览器验证了首页四步模块、首次访问记录、按钮与跳转、弹窗焦点、320/390/1024 像素布局、reduced motion 和存储/API 不可用的情况，无页面脚本错误。游戏完整五关浏览器验收已通过。

本包另行验证 ZIP、Linux LF 校验文件、逐文件摘要、首页引导和游戏构建资源，以及模拟发布目录内的预检、应用更新、回滚。以上本地验证不表示已在服务器部署；云端构建、健康状态与浏览器检查需上传后执行。

本地制作命令（在项目根目录，发布名不可重复）：

```powershell
python -m cloud_deployment.build_frontend_update --name GeneScope2_Onboarding_20261104_v1 --instructions cloud_deployment/ONBOARDING_SERVER_UPDATE.md
python reports/gene-hunter/validate_upload_package.py --name GeneScope2_Onboarding_20261104_v1 --require-onboarding
```
