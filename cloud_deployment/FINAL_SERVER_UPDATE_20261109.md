# GeneScope 2.0 最终版服务器更新（2026-11-09）

本版仅清理网站上的免责声明、能力边界和防御性提示。数据、模型、计算流程、接口、布局样式、导航、小游戏计分及原免登录配置沿用上一版。

更新包：`GeneScope2_Final_20261109_v1.zip`，配套校验文件：`GeneScope2_Final_20261109_v1.zip.sha256`。

## 服务器直接下载并更新

在 Workbench 连接服务器后执行整段命令。下载、校验或应用失败时只退出子 Shell，当前 Workbench 会话保留。

```bash
bash <<'SH'
set -eu
cd /root
name=GeneScope2_Final_20261109_v1
base=https://raw.githubusercontent.com/wujiangbin0604-cmyk/bioproject/main/server_updates
curl --http1.1 -fL --connect-timeout 15 --max-time 120 --retry 3 -o "$name.zip" "$base/$name.zip"
curl --http1.1 -fL --connect-timeout 15 --max-time 120 --retry 3 -o "$name.zip.sha256" "$base/$name.zip.sha256"
sha256sum -c "$name.zip.sha256"
update_dir=$(mktemp -d /root/genescope-final-20261109-XXXXXX)
python3 -m zipfile -e "$name.zip" "$update_dir"
python3 "$update_dir/apply_server_update.py" \
  --release /opt/genescope/releases/20261103-genescope2-v3 \
  --gateway-dir /opt/genescope/gateway/20261102-ip-https \
  --apply
SH
```

也可以先把 ZIP 和校验文件上传到 `/root`，从 `sha256sum -c` 开始执行。部署目录不同则替换 `--release` 和 `--gateway-dir`。更新前等待运行中的实验结束。

应用工具会校验现有发布文件、自动备份前端、构建应用容器，并检查 API 与 HTTPS。网站已经免登录时，网关配置保持原样；仍为上一版密码网关时，沿用既有免登录切换流程。更新包不携带数据矩阵、模型或密钥。

## 验收

打开 [https://47.243.232.201/](https://47.243.232.201/) 并按 `Ctrl+Shift+R` 刷新。检查首页、预测、特征分析、原研究档案、关于项目和基因猎手；数据集切换、实验配置和图表交互保持原有行为。

```bash
curl -fsS http://127.0.0.1:18080/api/v1/health
curl --noproxy '*' --connect-to 47.243.232.201:443:127.0.0.1:443 \
  -fsS -o /dev/null -w '%{http_code}\n' https://47.243.232.201/
```

## 回滚

使用更新器输出的实际前端备份路径，将下面的 `frontend-backup-实际目录` 替换后执行：

```bash
python3 /root/genescope-final-20261109-实际目录/update_frontend.py \
  --release /opt/genescope/releases/20261103-genescope2-v3 \
  --rollback /opt/genescope/releases/frontend-backup-实际目录
cd /opt/genescope/releases/20261103-genescope2-v3
docker compose -f compose.genescope2.yaml build web && \
docker compose -f compose.genescope2.yaml up -d --no-deps --no-build web
```

前端回滚不改变持久化实验、数据或模型。

## 本地重建

```powershell
npm --prefix frontend run build
python -m cloud_deployment.build_frontend_update --name GeneScope2_Final_新的版本名 --instructions cloud_deployment/FINAL_SERVER_UPDATE_20261109.md --public-access
```
