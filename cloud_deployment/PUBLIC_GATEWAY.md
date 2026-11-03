# 香港服务器公网 IP HTTPS 与密码网关

适用于已完成私有预览验收的 v3 包。本次目标 IP 为 `47.243.232.201`。应用继续监听 `127.0.0.1:8080`，外部访问经 Caddy 2.11.7 网关；已有 Docker 镜像、冻结模型和研究结果均不改写，也不执行训练或保留集评价。

安装器修订说明：首版漏写了Docker容器内的`caddy`可执行程序名，导致密码哈希命令以127退出。官方镜像没有ENTRYPOINT，因此所有`docker run`中的命令和Compose的command均须以`caddy`开头；本版已修复密码哈希、两处配置校验和网关启动调用。失败发生在创建网关目录和写入密码哈希之前，因此该失败不会保存输入的密码，也不会启动公网服务。

## 服务器准备检查

2026-11-02 用户提供的输出显示：80/443 无监听，UFW inactive，可用内存约872MiB。公网安全组是否放行尚需在阿里云控制台确认。不要启用一个未配置好SSH规则的防火墙，以免断开现有连接。

先将随附的 `public_gateway.py` 通过 Workbench 上传到服务器 `/root/public_gateway.py`，核对本机提供的 SHA-256，再在交互终端执行：

```bash
python3 /root/public_gateway.py --ip 47.243.232.201
```

程序会核对原包、拉取官方 Caddy 镜像、要求在终端两次隐藏输入网页访问密码（至少16字符、最多72个UTF-8字节）、生成bcrypt哈希并校验Caddy配置。用户名固定为 `genescope`。不要把密码、`users.caddy` 或完整生成配置发送到聊天或GitHub。密码不进入命令行参数和环境变量，不写入明文文件。

准备完成后生成 `/opt/genescope/gateway/20261102-ip-https/`：

- `Caddyfile`：公网IP HTTPS、公有ACME签发、密码认证、来源检查及冻结推理代理。
- `users.caddy`：仅服务器本地保存的bcrypt哈希，权限0600。
- `compose.gateway.json`：独立网关Compose项目，证书保存在持久化Docker卷中。
- `compose.app.override.json`：只补充HTTPS来源地址并再次明确关闭现场训练。

JSON是合法的Compose/YAML输入格式。准备步骤不重启应用、不发布公网端口；重复准备会拒绝覆盖已有密码文件。

## 开放端口与启动

阿里云ECS控制台 → 香港实例 → 安全组 → 入方向，新增两条允许规则：TCP 80、TCP 443，IPv4授权对象 `0.0.0.0/0`。80用于HTTP-01证书验证及重定向，443提供有密码保护的HTTPS；22保留原有SSH规则。应用8080、API8000和前端5173继续不向公网开放。无需开放UDP443，网关仅使用HTTP/1.1与HTTP/2。

然后执行：

```bash
python3 /root/public_gateway.py --ip 47.243.232.201 --activate
docker compose -f /opt/genescope/gateway/20261102-ip-https/compose.gateway.json logs --tail=60 gateway
```

启动时先重新校验生成配置；用原镜像重建应用容器以加入明确的HTTPS来源地址，不重新构建镜像；确认健康接口正常且现场训练关闭后，再启动网关。该步骤可能使现有SSH预览短暂重连。

## 证书和登录验收

Let’s Encrypt 已支持公网IP证书，需要shortlived配置，当前有效期约160小时。Caddy负责自动续期；80/443和证书持久化卷需继续可用。配置显式使用公有ACME issuer，防止裸IP默认获得内部CA证书，并设置default_sni适配裸IP及云主机NAT。

先在服务器检查可信证书与未登录访问，保留正常证书校验：

```bash
curl --noproxy '*' --connect-to 47.243.232.201:443:127.0.0.1:443 -sS -o /dev/null -w '%{http_code}\n' https://47.243.232.201/api/v1/health
```

预期401。此命令使用服务器本机连接并仍按公网IP验证证书，避免云公网IP回环路由问题。不要添加`-k`。签发尚未完成时先读网关日志，不能跳过证书错误后输入密码。

浏览器访问 `https://47.243.232.201/lab`，应先出现浏览器原生登录框；用户名 `genescope`，密码为刚刚在服务器设置的密码。之后验收页面、历史图表、六模型状态以及已有开发样本推理；现场训练继续不可用。

命令行登录检查只把用户名放入参数，curl会交互询问密码：

```bash
curl --noproxy '*' --connect-to 47.243.232.201:443:127.0.0.1:443 -fsS -u genescope https://47.243.232.201/api/v1/health
curl --noproxy '*' --connect-to 47.243.232.201:443:127.0.0.1:443 -fsS -u genescope https://47.243.232.201/api/v1/lab/models
```

当前网关将上游连接数上限设为2；这不等同于按用户的请求频率配额，尚未进行公网并发负载与长期续期验收。单账号密码保护适合课程演示；账号不要使用服务器root密码。Basic Auth不提供独立的网页退出按钮，结束演示应关闭浏览器会话。

## 恢复到SSH私有预览

```bash
docker compose -f /opt/genescope/gateway/20261102-ip-https/compose.gateway.json stop gateway
docker compose -f /opt/genescope/releases/20261102-preview-v3/compose.yaml up -d --no-build --no-deps web
```

此操作不删除证书卷和模型文件。不要执行`down -v`来排查证书问题。现有SSH转发方式继续可用。以后购买域名可单独规划迁移，不根据上线期间的预测结果改动冻结模型。

## 官方依据

- [Let’s Encrypt：公网IP与短期证书](https://letsencrypt.org/2026/01/15/6day-and-ip-general-availability)
- [Caddy：ACME issuer与profile](https://caddyserver.com/docs/caddyfile/directives/tls)
- [Caddy：Basic Authentication](https://caddyserver.com/docs/caddyfile/directives/basic_auth)
- [Caddy：default_sni](https://caddyserver.com/docs/caddyfile/options#default-sni)
- [Caddy 2.11.7 官方发布](https://github.com/caddyserver/caddy/releases/tag/v2.11.7)
