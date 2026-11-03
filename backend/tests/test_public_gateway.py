"""公网网关边界检查；不访问原始表达数据或训练任何模型。"""
import json
import subprocess
from types import SimpleNamespace

import pytest

from cloud_deployment.public_gateway import public_ipv4, render_caddy, render_compose, render_override


@pytest.mark.parametrize("value", ["127.0.0.1", "10.0.0.1", "0.0.0.0", "::1", "47.1.1.1\nadmin off", "example.org"])
def test_reject_unsafe_or_non_public_target(value):
    with pytest.raises(ValueError):
        public_ipv4(value)


def test_ip_https_uses_public_issuer_and_keeps_inference_protected():
    config = render_caddy("47.243.232.201")
    assert "https://47.243.232.201" in config
    assert "profile shortlived" in config and "issuer acme https://acme-v02.api.letsencrypt.org/directory" in config
    assert "tls internal" not in config
    assert config.index("basic_auth") < config.index("reverse_proxy")
    assert "127.0.0.1:8080" in config and "max_conns_per_host 2" in config
    assert "respond @training" in config and "respond @bad_origin" in config
    assert "admin off" in config
    assert "default_sni 47.243.232.201" in config


def test_gateway_has_no_model_mount_and_retains_certificate_storage():
    data = render_compose()
    gateway = data["services"]["gateway"]
    assert data["name"] == "genescope-edge"
    assert gateway["network_mode"] == "host"
    assert gateway["read_only"] and gateway["mem_limit"] == "192m"
    assert "caddy_data:/data" in gateway["volumes"]
    assert not any("docker.sock" in v or "models" in v or "/app" in v for v in gateway["volumes"])


def test_application_override_changes_only_origins_and_keeps_training_off():
    data = render_override("47.243.232.201")
    env = data["services"]["web"]["environment"]
    assert env["GENESCOPE_LAB_TRAINING_ENABLED"] == "0"
    assert "https://47.243.232.201" in env["GENESCOPE_ALLOWED_ORIGINS"].split(",")
    assert set(data["services"]["web"]) == {"environment"}
    assert "password" not in json.dumps(data).lower()


@pytest.mark.parametrize("filename", ["Caddyfile", "compose.gateway.json", "compose.app.override.json"])
def test_changed_gateway_configuration_cannot_trigger_startup(tmp_path, monkeypatch, filename):
    import cloud_deployment.public_gateway as gateway
    ip = "47.243.232.201"
    (tmp_path / "Caddyfile").write_text(render_caddy(ip), encoding="utf-8")
    for name, content in (("compose.gateway.json", render_compose()),
                          ("compose.app.override.json", render_override(ip))):
        (tmp_path / name).write_text(json.dumps(content), encoding="utf-8")
    changed = "admin off\n" if filename == "Caddyfile" else "{}"
    (tmp_path / filename).write_text(changed, encoding="utf-8")
    monkeypatch.setattr(gateway.sys, "platform", "linux")
    monkeypatch.setattr(gateway, "validate_existing_release", lambda _: None)
    calls = []
    monkeypatch.setattr(gateway, "run", lambda *a, **k: calls.append(a))
    with pytest.raises(ValueError):
        gateway.activate(ip, tmp_path, tmp_path)
    assert calls == []


def test_compose_can_execute_on_official_image_without_entrypoint():
    """官方镜像 Entrypoint=null，Compose 的第一个参数必须是可执行程序。"""
    command = render_compose()["services"]["gateway"]["command"]
    assert command[:2] == ["caddy", "run"]


def test_prepare_runs_complete_executable_commands_with_no_image_entrypoint(tmp_path, monkeypatch):
    """通过实际 prepare 调用点检查 argv，复现镜像无 ENTRYPOINT 的执行约定。"""
    import cloud_deployment.public_gateway as gateway
    from unittest.mock import MagicMock
    ip = "47.243.232.201"
    monkeypatch.setattr(gateway.sys, "platform", "linux")
    monkeypatch.setattr(gateway.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(gateway, "validate_existing_release", lambda _: None)
    monkeypatch.setattr(gateway.socket, "socket", MagicMock())
    monkeypatch.setattr(gateway.getpass, "getpass", lambda _: "fixture-only-long-password")
    container_commands = []

    def fake_docker(args, **kwargs):
        stdout = ""
        if args[:2] == ["docker", "run"]:
            command = args[args.index(gateway.CADDY_IMAGE) + 1:]
            container_commands.append(command)
            # 不是安装器的实现规则，而是已确认的官方 OCI 镜像执行约定。
            if not command or command[0] != "caddy":
                raise subprocess.CalledProcessError(127, args, stderr="executable file not found")
            if command[1] == "hash-password":
                assert kwargs["input"] == "fixture-only-long-password\n"
                stdout = "$2a$12$" + "A" * 53 + "\n"  # 仅测试夹具，不用于真实认证。
        elif args[:2] == ["docker", "compose"]:
            stdout = json.dumps({"services": {"web": {
                "environment": render_override(ip)["services"]["web"]["environment"],
                "ports": [{"host_ip": "127.0.0.1", "published": "8080"}],
            }}})
        elif args[:3] == ["docker", "image", "inspect"]:
            stdout = json.dumps([{"Id": "fixture-image", "RepoDigests": []}])
        return subprocess.CompletedProcess(args, 0, stdout, "")

    monkeypatch.setattr(gateway.subprocess, "run", fake_docker)
    output = tmp_path / "gateway"
    gateway.prepare(ip, tmp_path, output)
    assert [args[1] for args in container_commands] == ["hash-password", "validate"]
    assert json.loads((output / "compose.gateway.json").read_text())["services"]["gateway"]["command"][:2] == ["caddy", "run"]
