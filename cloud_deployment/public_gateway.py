"""为已有私有预览增加 IP HTTPS 与密码网关；不构建或训练任何模型。"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

CADDY_IMAGE = "caddy:2.11.7-alpine"
APP_IMAGE = "genescope:hk-preview-v3"
RELEASE_NAME = "GeneScope_HK_preview_20261102_v3"
USERNAME = "genescope"


def public_ipv4(value: str) -> str:
    """仅允许公网 IPv4，防止配置注入以及误向内网申请公有证书。"""
    address = ipaddress.IPv4Address(value)
    if not address.is_global:
        raise ValueError("必须填写香港 ECS 当前公网 IPv4")
    return str(address)


def render_caddy(ip: str, training_enabled: bool = False) -> str:
    ip = public_ipv4(ip)
    # 显式指定 ACME issuer，避免裸 IP 使用内部 CA；HTTP-01 需要公网 TCP 80。
    return """{
    admin off
    default_sni PUBLIC_IP
    servers {
        protocols h1 h2
        max_header_size 16KB
        timeouts {
            read_header 10s
            read_body 30s
            write WRITE_TIMEOUT
            idle 60s
        }
    }
}

https://PUBLIC_IP {
    tls {
        issuer acme https://acme-v02.api.letsencrypt.org/directory {
            profile shortlived
            disable_tlsalpn_challenge
        }
    }
    header {
        -Server
        X-Content-Type-Options nosniff
        X-Frame-Options SAMEORIGIN
        Referrer-Policy same-origin
    }
    route {
        basic_auth {
            import /etc/genescope/users.caddy
        }
TRAINING_GUARD
        @bad_origin {
            method POST
            header Origin *
            not header Origin https://PUBLIC_IP
        }
        respond @bad_origin "Origin is not allowed." 403
        @other_methods not method GET HEAD OPTIONS POST
        respond @other_methods "Method is not allowed." 405
        @other_posts {
            method POST
            not path POST_PATHS
        }
        respond @other_posts "Only frozen inference is enabled." 405
        request_body {
            max_size 6MB
        }
        reverse_proxy 127.0.0.1:8080 {
            header_up -Authorization
            header_up -Cookie
            header_up -Forwarded
            header_up -X-Forwarded-For
            header_up -X-Forwarded-Proto
            transport http {
                dial_timeout 5s
                response_header_timeout 120s
                max_conns_per_host UPSTREAM_CONNECTIONS
            }
        }
    }
}
""".replace("PUBLIC_IP", ip).replace("WRITE_TIMEOUT", "0" if training_enabled else "150s").replace(
        "TRAINING_GUARD", "" if training_enabled else '''        @training {
            method POST
            path /api/v1/lab/tasks /api/v1/lab/tasks/*
        }
        respond @training "Live training is disabled in this deployment." 403''').replace(
        "POST_PATHS", "/api/v1/predict /api/v1/lab/predict" + (
            " /api/v1/lab/tasks /api/v1/lab/tasks/*/cancel" if training_enabled else "")).replace(
        "UPSTREAM_CONNECTIONS", "16" if training_enabled else "2")


def render_compose() -> dict:
    """独立 Compose 项目，只增加网关；不挂载应用、模型和 Docker socket。"""
    return {
        "name": "genescope-edge",
        "services": {"gateway": {
            "image": CADDY_IMAGE,
            "init": True,
            "restart": "unless-stopped",
            "network_mode": "host",
            "command": ["caddy", "run", "--config", "/etc/genescope/Caddyfile", "--adapter", "caddyfile"],
            "volumes": ["./Caddyfile:/etc/genescope/Caddyfile:ro",
                        "./users.caddy:/etc/genescope/users.caddy:ro",
                        "caddy_data:/data", "caddy_config:/config"],
            "environment": {"GOMAXPROCS": "1", "GOMEMLIMIT": "128MiB"},
            "mem_limit": "192m", "cpus": 0.5, "pids_limit": 64,
            "read_only": True, "tmpfs": ["/tmp:rw,nosuid,nodev,size=16m,mode=1777"],
            "cap_drop": ["ALL"], "cap_add": ["NET_BIND_SERVICE"],
            "security_opt": ["no-new-privileges:true"],
            "logging": {"driver": "json-file", "options": {"max-size": "5m", "max-file": "3"}},
            "stop_grace_period": "20s",
        }},
        "volumes": {"caddy_data": {}, "caddy_config": {}},
    }


def render_override(ip: str) -> dict:
    ip = public_ipv4(ip)
    return {"services": {"web": {"environment": {
        "GENESCOPE_LAB_TRAINING_ENABLED": "0",
        "GENESCOPE_ALLOWED_ORIGINS":
            "http://127.0.0.1:8080,http://localhost:8080," + f"https://{ip}",
    }}}}


def run(args: list[str], *, cwd: Path | None = None, capture: bool = False):
    """不经 shell 执行命令；不将密码放入参数、环境变量或日志。"""
    return subprocess.run(args, cwd=cwd, check=True, text=True, encoding="utf-8",
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None)


def validate_existing_release(release: Path) -> None:
    metadata = json.loads((release / "bundle_manifest.json").read_text(encoding="utf-8"))
    if metadata.get("release") != RELEASE_NAME:
        raise ValueError("当前安装器仅适用于已验收的 v3 上传包")
    run([sys.executable, "-m", "cloud_deployment.verify"], cwd=release)
    current = json.loads(run(["docker", "compose", "-f", str(release / "compose.yaml"),
                             "config", "--format", "json"], capture=True).stdout)
    web = current["services"]["web"]
    if web.get("image") != APP_IMAGE or web.get("environment", {}).get("GENESCOPE_LAB_TRAINING_ENABLED") != "0":
        raise ValueError("原有镜像或关闭训练的配置不符，停止公网配置")
    ports = web.get("ports", [])
    if len(ports) != 1 or ports[0].get("host_ip") != "127.0.0.1" or str(ports[0].get("published")) != "8080":
        raise ValueError("应用必须继续只发布在 127.0.0.1:8080")
    run(["docker", "image", "inspect", APP_IMAGE], capture=True)


def prepare(ip: str, release: Path, destination: Path) -> None:
    ip = public_ipv4(ip)
    if sys.platform != "linux":
        raise ValueError("实际安装只能在香港 Ubuntu 服务器执行")
    release = release.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError("网关目录已存在；保留已有密码和证书配置，不自动覆盖")
    validate_existing_release(release)
    for port in (80, 443):
        with socket.socket() as probe:
            probe.bind(("0.0.0.0", port))
    run(["docker", "pull", CADDY_IMAGE])
    if not sys.stdin.isatty():
        raise ValueError("请在交互终端运行，密码需要隐藏输入；不要通过管道传入密码")
    password = getpass.getpass("设置网页访问密码（至少16字符，输入不显示）：")
    confirmation = getpass.getpass("再次输入网页访问密码：")
    if password != confirmation or len(password) < 16 or len(password.encode("utf-8")) > 72:
        raise ValueError("两次密码须一致、至少16字符且不超过72个UTF-8字节")
    hashed = subprocess.run(["docker", "run", "--rm", "-i", "--network", "none", CADDY_IMAGE,
                             "caddy", "hash-password", "--algorithm", "bcrypt", "--bcrypt-cost", "12"],
                            input=password + "\n", text=True, encoding="utf-8",
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout.strip()
    password = confirmation = None
    if re.fullmatch(r"\$2[aby]\$12\$[./A-Za-z0-9]{53}", hashed) is None:
        raise ValueError("密码哈希输出格式不符，停止")
    os.umask(0o077)
    destination.mkdir(parents=True, mode=0o700)
    (destination / "Caddyfile").write_text(render_caddy(ip), encoding="utf-8")
    (destination / "users.caddy").write_text(f"{USERNAME} {hashed}\n", encoding="utf-8")
    for name, content in (("compose.gateway.json", render_compose()),
                          ("compose.app.override.json", render_override(ip))):
        (destination / name).write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    run(["docker", "run", "--rm", "--network", "none", "-v", f"{destination}:/etc/genescope:ro",
         CADDY_IMAGE, "caddy", "validate", "--config", "/etc/genescope/Caddyfile", "--adapter", "caddyfile"])
    combined = json.loads(run(["docker", "compose", "-f", str(release / "compose.yaml"),
                              "-f", str(destination / "compose.app.override.json"),
                              "config", "--format", "json"], capture=True).stdout)
    if combined["services"]["web"]["environment"]["GENESCOPE_LAB_TRAINING_ENABLED"] != "0" or combined["services"]["web"]["ports"][0]["host_ip"] != "127.0.0.1":
        raise ValueError("合并后配置未保持训练关闭和本机端口绑定，停止")
    audit = {"stage": "prepared_not_started", "public_ip": ip, "username": USERNAME,
             "caddy_image": CADDY_IMAGE, "application_image": APP_IMAGE,
             "application_release": str(release), "training_enabled": False,
             "models_retrained": False, "test_set_reevaluated": False,
             "configuration_sha256": {name: hashlib.sha256((destination / name).read_bytes()).hexdigest()
                                      for name in ("Caddyfile", "compose.gateway.json", "compose.app.override.json")}}
    for label, image in (("application", APP_IMAGE), ("caddy", CADDY_IMAGE)):
        image_info = json.loads(run(["docker", "image", "inspect", image], capture=True).stdout)[0]
        audit[label + "_image_id"] = image_info["Id"]
        audit[label + "_repo_digests"] = image_info.get("RepoDigests", [])
    (destination / "gateway_configuration.json").write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    # 准备阶段不发布端口、不重启应用。启动前可检查生成的配置。
    print(f"PREPARED: {destination}")
    print(f"URL after activation: https://{ip}/lab")
    print(f"Login username: {USERNAME}; password is not logged")
    print("公网HTTPS尚未启动；下一步放行TCP 80/443并执行启动命令。")


def activate(ip: str, release: Path, destination: Path) -> None:
    """仅在显式启动参数下重建应用环境配置并启动网关，镜像不重新构建。"""
    ip = public_ipv4(ip)
    if sys.platform != "linux":
        raise ValueError("实际启动只能在香港 Ubuntu 服务器执行")
    release = release.resolve(strict=True)
    destination = destination.resolve(strict=True)
    validate_existing_release(release)
    expected = {"compose.gateway.json": render_compose(), "compose.app.override.json": render_override(ip)}
    for name, content in expected.items():
        if json.loads((destination / name).read_text(encoding="utf-8")) != content:
            raise ValueError(f"生成的配置已变化，停止自动启动：{name}")
    if (destination / "Caddyfile").read_text(encoding="utf-8") != render_caddy(ip):
        raise ValueError("Caddyfile 与本次 IP 配置不一致，停止自动启动")
    users = destination / "users.caddy"
    if users.stat().st_mode & 0o077 or re.fullmatch(r"genescope \$2[aby]\$12\$[./A-Za-z0-9]{53}\n", users.read_text(encoding="utf-8")) is None:
        raise ValueError("密码文件权限或哈希格式不符，停止自动启动")
    run(["docker", "run", "--rm", "--network", "none", "-v", f"{destination}:/etc/genescope:ro",
         CADDY_IMAGE, "caddy", "validate", "--config", "/etc/genescope/Caddyfile", "--adapter", "caddyfile"])
    run(["docker", "compose", "-f", str(release / "compose.yaml"),
         "-f", str(destination / "compose.app.override.json"),
         "up", "-d", "--no-build", "--no-deps", "web"])
    # 健康检查仅访问状态接口；不传入表达数据，不调用任何 fit 或保留集评价。
    for attempt in range(25):
        try:
            with urlopen("http://127.0.0.1:8080/api/v1/health", timeout=2) as response:
                health = json.load(response)
            if health["data"]["api"] == "ok" and health["data"]["model_available"]:
                break
        except (OSError, ValueError, KeyError):
            pass
        if attempt == 24:
            raise ValueError("应用尚未就绪，未启动公网网关；请检查应用日志")
        time.sleep(1)
    with urlopen("http://127.0.0.1:8080/api/v1/lab/capabilities", timeout=10) as response:
        capabilities = json.load(response)
    if capabilities.get("available") is not False:
        raise ValueError("现场训练未保持禁用，未启动公网网关")
    run(["docker", "compose", "-f", str(destination / "compose.gateway.json"), "up", "-d", "--no-build"])
    run(["docker", "compose", "-f", str(destination / "compose.gateway.json"), "ps"])
    audit_path = destination / "gateway_configuration.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["stage"] = "gateway_started_certificate_and_public_access_pending_acceptance"
    audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(f"网关进程已启动；证书签发及公网访问仍需验收：https://{ip}/lab")
    print("不要使用 -k 或忽略浏览器证书警告；若证书尚未签发，请查看网关日志。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ip", required=True)
    parser.add_argument("--release", type=Path, default=Path("/opt/genescope/releases/20261102-preview-v3"))
    parser.add_argument("--output", type=Path, default=Path("/opt/genescope/gateway/20261102-ip-https"))
    parser.add_argument("--activate", action="store_true", help="启动已准备并校验的配置；不重新设置密码或构建镜像")
    args = parser.parse_args()
    try:
        if args.activate:
            activate(args.ip, args.release, args.output)
        else:
            prepare(args.ip, args.release, args.output)
    except subprocess.CalledProcessError as exc:
        # 不输出捕获的 stdout/stderr，防止错误处理泄漏哈希或环境配置。
        print(f"外部命令失败：{exc.cmd[0]} {exc.cmd[1]}，退出码 {exc.returncode}；请检查前面的校验信息。", file=sys.stderr)
        raise SystemExit(1) from None
    except (OSError, ValueError, KeyError) as exc:
        print(f"网关准备失败：{type(exc).__name__}：{exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
