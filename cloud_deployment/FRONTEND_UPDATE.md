# GeneScope 2 视觉升级：静态前端更新

此包只更新 `frontend/dist` 和发布清单中对应的前端摘要。后端API、数据、实验状态、模型、HTTPS网关及密码保持现有配置。更新前逐项校验原发布文件，原前端备份到发布目录外。执行时不要启动训练任务。

## 在 Workbench 上传并执行

上传 `GeneScope2_UI_20261104_v2.zip` 和同名 `.sha256` 文件到 `/root`。执行：

```bash
cd /root
sha256sum -c GeneScope2_UI_20261104_v2.zip.sha256
mkdir -p /root/genescope-ui-20261104
unzip -q GeneScope2_UI_20261104_v2.zip -d /root/genescope-ui-20261104

python3 /root/genescope-ui-20261104/update_frontend.py \
  --release /opt/genescope/releases/20261103-genescope2-v3

python3 /root/genescope-ui-20261104/update_frontend.py \
  --release /opt/genescope/releases/20261103-genescope2-v3 --apply

cd /opt/genescope/releases/20261103-genescope2-v3
docker compose -f compose.genescope2.yaml build web
docker compose -f compose.genescope2.yaml up -d --no-deps web

curl -fsS --retry 12 --retry-delay 5 --retry-max-time 90 --max-time 10 \
  http://127.0.0.1:18080/api/v1/health
docker compose -f compose.genescope2.yaml ps
```

每条命令成功后再执行下一条；校验或构建失败时先停止，保留现有容器。构建会复用既有依赖层，无需在服务器安装Node。启动最初数秒可能返回502，健康检查成功后使用原账号密码打开 `https://47.243.232.201`，按 `Ctrl+Shift+R` 刷新。网关不需要重新激活。

更新输出中的 `backup` 是旧前端和原发布清单的备份位置。更新文件不会覆盖 `/opt/genescope/state-v2`，已有实验和模型继续使用。

## 回滚

将下面的备份路径替换成更新时输出的实际 `backup`，校验通过后会恢复旧静态前端：

```bash
python3 /root/genescope-ui-20261104/update_frontend.py \
  --release /opt/genescope/releases/20261103-genescope2-v3 \
  --rollback /opt/genescope/releases/frontend-backup-实际备份目录名

cd /opt/genescope/releases/20261103-genescope2-v3
docker compose -f compose.genescope2.yaml build web
docker compose -f compose.genescope2.yaml up -d --no-deps web
```

## 本地重建更新包

```powershell
npm --prefix frontend run build
python -m cloud_deployment.build_frontend_update --name GeneScope2_UI_新的版本名
```

输出到 `cloud_deployment/dist`，不包含表达矩阵或模型文件。打包工具不会覆盖同名发布包。
