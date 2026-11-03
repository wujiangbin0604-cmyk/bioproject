# GeneScope 2.0 香港服务器升级操作

目标：原47.243.232.201，Ubuntu22.04/x86_64，2核约2GiB；已有Caddy HTTPS和密码网关。采用Workbench手动上传；本机SSH密钥未获授权，本次没有代登录或宣称已上线。

## 1. 上传与校验

将本机 `cloud_deployment/dist/GeneScope2_20261103_v3.zip` 和同名 `.zip.sha256` 上传到服务器 `/root/`。这是私有运行包，含真实处理表达矩阵、模型与实验，不上传到GitHub；不包含161例PANCAN保留表达、原始压缩归档、密码或SSH密钥。包内保留Arco Design Pro许可和来源声明。

在Workbench终端执行：

```bash
cd /root
sha256sum -c GeneScope2_20261103_v3.zip.sha256
mkdir -p /opt/genescope/releases
mkdir /opt/genescope/releases/20261103-genescope2-v3
python3 -m zipfile -e /root/GeneScope2_20261103_v3.zip /opt/genescope/releases/20261103-genescope2-v3
cd /opt/genescope/releases/20261103-genescope2-v3
python3 -m cloud_deployment.platform2_release verify
```

必须使用Python解压以保留中文路径；不覆盖原发布目录。若目录已存在，先核查已有内容，另选新发布目录，不删除旧版本。

## 2. 构建和初始化

```bash
docker compose -f compose.genescope2.yaml config
docker compose -f compose.genescope2.yaml --progress plain build
python3 -m cloud_deployment.platform2_release initialize
docker compose -f compose.genescope2.yaml up -d
docker compose -f compose.genescope2.yaml ps
docker compose -f compose.genescope2.yaml logs --tail=80 web
```

容器固定Python3.14.0，科学计算依赖与冻结工件匹配；构建会检查发布内容及原M0–M5，不重训这些模型、不绕过哈希。服务器无需Node.js，frontend/dist已在Windows构建。镜像下载或Linux轮子不可用时保留原服务，贴出错误再处理。

持久化数据在`/opt/genescope/state-v2`，与发布目录分离。初始化仅复制缺失文件，不覆盖已有数据、模型或实验；对非空且无GeneScope标记的目录直接拒绝。PANCAN的640行开发包复用原缓存硬链接，不复制保留表达值。代码和原研究汇总只读；运行数据使用uid10001。

## 3. 本机验收（不切换公网）

```bash
curl -fsS http://127.0.0.1:18080/api/v1/health
curl -fsS http://127.0.0.1:18080/api/v1/datasets
curl -fsS http://127.0.0.1:18080/api/v1/models
docker compose -f compose.genescope2.yaml exec -T web python -m cloud_deployment.platform2_release runtime
```

应看到API正常、冻结M1可用、四数据集ready；runtime命令会核验原六模型与每套数据集的一个新模型，并用实际已知样本测试推理，不报告其为独立泛化成绩。

新版本仅监听127.0.0.1:18080，原版本8080继续服务。可以在本机PowerShell运行`ssh -N -L 18080:127.0.0.1:18080 root@47.243.232.201`，在自己的SSH提示中输入密码，浏览http://127.0.0.1:18080。无需对公网开放18080、8000、5173。

## 4. 切换现有HTTPS网关

确认上一节全部通过，再执行：

```bash
python3 -m cloud_deployment.platform2_gateway activate --ip 47.243.232.201
curl --noproxy '*' --connect-to 47.243.232.201:443:127.0.0.1:443 -sS -o /dev/null -w '%{http_code}\n' https://47.243.232.201/api/v1/health
```

未登录应返回401，保留正常证书校验，不加-k。脚本先验证新后端、四数据集、候选Caddy配置，备份原Caddyfile，再重建网关容器。保留原users.caddy与证书卷。新增放行受密码保护的v2任务/取消/导入端点，继续来源检查；SSE关闭写超时，导入单独支持大文件。旧的仅推理网关规则不能直接复用，否则开始实验会被拒绝。

浏览器访问https://47.243.232.201，使用原genescope用户名和网站密码，进入数据集中心与实验室。

在2GiB服务器上，验收后停止旧版应用以释放内存，保留其镜像/目录：

```bash
docker compose -f /opt/genescope/releases/20261102-preview-v3/compose.yaml stop web
```

若旧发布目录与此不同，使用原实际compose路径，先检查，不猜测目录。不执行down -v、不删除旧镜像或证书。新版容器1536MiB、1.25CPU，训练单并发、单线程、工作进程采样内存1024MiB、可用内存至少512MiB、900秒上限。旧服务未停止时可能因主机可用内存不足拒绝训练；不要通过无限提高上限规避。

## 5. 真实训练与SSE验收

先在浏览器选择GSE45827、LinearSVC、ANOVA、K20、3折运行一次。任务应逐折变化，刷新后仍可查询，完成后进入历史与模型对比。再测试取消一个RF任务，确认实际停止；不要直接在2GiB机器启动重复大批量全特征实验。

命令行也可验证（curl只包含用户名，会在终端提示输入网站密码）：

```bash
curl --noproxy '*' -u genescope -H 'Content-Type: application/json' -d '{"dataset_id":"gse45827","algorithms":["linear_svc"],"selection":"anova","k":20,"folds":3,"seed":42,"repeats":1}' https://47.243.232.201/api/v1/experiments
# 使用上一步返回的真实任务ID
curl --noproxy '*' -N -u genescope https://47.243.232.201/api/v1/experiments/任务ID/events
```

上述Linux容器构建、健康状态、网关和训练必须在服务器实际执行后才算云部署通过；本机包校验不能替代。

## 6. 回滚

先启动原版本，再恢复原网关：

```bash
docker compose -f /opt/genescope/releases/20261102-preview-v3/compose.yaml up -d --no-build web
python3 -m cloud_deployment.platform2_gateway rollback
docker compose -f compose.genescope2.yaml stop web
```

原密码、证书和v2数据仍保留。新版停止后可再次启动，不丢历史记录。不要为了回滚清空state-v2。

## 从源码重新制作私有包

在已安装依赖、导入四数据集并有受信模型的工作区：

```powershell
npm --prefix frontend run build
$env:PYTHONPATH=(Resolve-Path backend/.vendor314).Path
& "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe" -m cloud_deployment.build_genescope2 --release GeneScope2_新的发布名
```

GitHub只保存源码与受控冻结模型；克隆代码不等于下载了本地表达矩阵、训练产物或历史私有结果。完整部署使用上述白名单包，不直接把整个工作目录压缩上传。

依据：[Docker构建上下文与dockerignore](https://docs.docker.com/build/concepts/context/)、[Compose健康状态](https://docs.docker.com/compose/how-tos/startup-order/)、[Caddy反向代理与流式响应](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)。
