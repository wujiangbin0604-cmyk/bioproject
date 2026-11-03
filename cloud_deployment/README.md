# 香港服务器第一阶段：历史展示与六模型推理预览

适用于已确认的Ubuntu22.04、x86_64、2核、约2GiB服务器。容器固定Python3.14.0，科学计算依赖与现有模型环境一致。当前阶段不打包原始表达矩阵，不启动现场CV，不重新训练冻结模型、不重新评价保留集。

## 上传与构建

在本机生成并验证的ZIP通过Workbench文件上传到服务器，例如 `/root/GeneScope_HK_preview_20261102_v3.zip`。从此ZIP部署，避免Git自动更改源代码换行，造成自定义类型的原字节摘要变化。

先在服务器核对ZIP的SHA-256与本机提供的摘要，再执行：

```bash
mkdir -p /opt/genescope/releases
mkdir /opt/genescope/releases/20261102-preview-v3
PYTHONUTF8=1 python3 -m zipfile -e /root/GeneScope_HK_preview_20261102_v3.zip /opt/genescope/releases/20261102-preview-v3
cd /opt/genescope/releases/20261102-preview-v3
python3 -m cloud_deployment.verify
docker compose config
docker compose --progress plain build
docker compose up -d
docker compose ps
```

构建中的 `python -m cloud_deployment.verify --models` 必须让六模型全部通过校验，否则构建失败。缺少Linux轮子、模型环境不符、源码/模型字节变化均明确停止；不要修改加载器摘要或放宽版本要求来强行启动。

### 中文路径解压注意事项

服务器首次使用 `unzip` 解压时，曾将两张热图的中文目录及文件名转成乱码；图片内容的SHA-256仍与清单一致，构建因此在内容校验阶段停止。原ZIP的UTF-8路径标记正确，后续统一使用上面的Python标准库解压命令，并在构建前运行内容校验。已失败的目录应保留以便排查；可将同一个已核验ZIP解压到一个新的发布目录，再校验、构建。不要修改可信摘要来接受乱码路径。

## 容器与接口验收

```bash
docker compose exec -T web python -m cloud_deployment.verify --models
curl -fsS http://127.0.0.1:8080/api/v1/health
curl -fsS http://127.0.0.1:8080/api/v1/lab/models
curl -fsS http://127.0.0.1:8080/api/v1/lab/capabilities
```

预期：API正常、M1可用、六模型全部available=true；现场训练available=false并有阶段说明。初次健康检查可能需要几十秒。日志：`docker compose logs --tail=100 web`。静态页面包含全部八个入口，训练选择器保留并明确禁用，不用模拟任务或模拟成绩代替。

当前内存限制为容器1024MiB、CPU1.5核；/tmp最大192MiB。容器以非root用户运行，代码和历史结果为只读。若健康检查出现OOM，应先检查资源及日志，调整需明确记录，不自动删结果或改模型。

## 浏览器查看

私有预览验收通过后，公网 IP HTTPS 与密码网关的配置见 [PUBLIC_GATEWAY.md](PUBLIC_GATEWAY.md)。两阶段配置独立保存，不修改已验收上传包和模型。

当前包只绑定服务器 `127.0.0.1:8080`，用于受限验收。不要为了公开访问直接改成0.0.0.0；公网HTTPS、身份验证和访问额度在后续阶段配置。

在你自己的Windows PowerShell中运行SSH端口转发：

```powershell
ssh -N -L 8080:127.0.0.1:8080 root@服务器公网IP
```

密码只在你自己的SSH登录提示中输入。保留该终端，在本机浏览器打开 `http://127.0.0.1:8080/lab`。若本机8080被占用，可把命令左侧8080改为18080，并打开 `http://127.0.0.1:18080/lab`。若SSH连接超时，检查云安全组的22端口是否允许你当前公网IP；无需开放8000、5173或8080。

## 包内容与限制

- 网页在本机构建，服务器不需要Node.js或执行npm安装。
- 六份冻结工件原字节复制；M1使用原加载器，其余五个使用已审查注册加载器。
- 仅带入网页适配器登记的历史汇总和两张开发集热图，不带入大规模OOF、检查点、原始表达CSV/TAR、凭据或本地虚拟环境。
- 历史错误变化源表可能含匿名sample ID，只保存在私有后端文件中；API返回汇总计数，Nginx只发布frontend/dist。
- 当前关闭现场训练；以后确认资源、开发数据隔离和公网权限后另行启用，不能仅修改开关就宣称已验收训练功能。
- 本机Windows验证和服务器Linux容器验证分开记录；只有云端构建、接口及真实推理通过后才称云部署验收通过。
