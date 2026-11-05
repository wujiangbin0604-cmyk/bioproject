"""Exercise the real update boundary and recovery without Docker, data or training."""
import hashlib
import json
import subprocess
from pathlib import Path
import zipfile

import pytest
from cloud_deployment import configure_public_access as access
from cloud_deployment.platform2_gateway import render


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    original = render('47.243.232.201')
    (tmp_path / 'Caddyfile').write_text(original, encoding='utf-8')
    (tmp_path / 'compose.gateway.json').write_text(json.dumps({'services': {'gateway': {'image': 'caddy:2.11.7-alpine'}}}), encoding='utf-8')
    (tmp_path / 'users.caddy').write_text('credential fixture, never parsed or changed', encoding='utf-8')
    calls = []
    monkeypatch.setattr(access, 'run', lambda args: calls.append(args))
    return tmp_path, original, calls


def test_only_the_known_auth_block_is_removed_and_all_other_rules_are_preserved():
    original = render('47.243.232.201')
    public = access.public_config(original)
    assert 'basic_auth' not in public and 'users.caddy' not in public
    assert original.replace('        basic_auth {\n            import /etc/genescope/users.caddy\n        }\n', '') == public
    for expected in ['issuer acme', 'profile shortlived', 'respond @bad_origin', 'request_body', 'reverse_proxy 127.0.0.1:18080', '/api/v1/experiments', '/api/v1/datasets/import']:
        assert expected in public
    assert access.public_config(public) == public


@pytest.mark.parametrize('bad', ['basic_auth {\n user hash\n}', 'basicauth {\n user hash\n}', 'import /etc/genescope/users.caddy'])
def test_unknown_auth_configuration_is_not_silently_rewritten(bad):
    text = render('47.243.232.201') + '\n' + bad
    with pytest.raises(ValueError):
        access.public_config(text)


def test_dry_run_only_validates_candidate_without_changing_gateway(gateway):
    folder, original, calls = gateway
    result = access.configure(folder)
    assert result['dry_run']
    assert (folder / 'Caddyfile').read_text(encoding='utf-8') == original
    assert len(calls) == 1 and 'validate' in calls[0] and 'hash-password' not in calls[0]
    assert 'users.caddy' not in ' '.join(calls[0])


def test_public_activation_is_idempotent_and_rolls_back_exact_bytes(gateway):
    folder, original, calls = gateway
    users = (folder / 'users.caddy').read_bytes()
    result = access.configure(folder, apply=True)
    assert result['website_login_required'] is False
    assert 'basic_auth' not in (folder / 'Caddyfile').read_text(encoding='utf-8')
    assert calls[-1][0] == 'curl' and '-u' not in calls[-1] and '-k' not in calls[-1]
    assert access.configure(folder, apply=True)['changed'] is False
    access.rollback(folder)
    assert (folder / 'Caddyfile').read_text(encoding='utf-8') == original
    assert (folder / 'users.caddy').read_bytes() == users


@pytest.mark.parametrize('failure', ['validate', 'restart', 'https'])
def test_failure_keeps_or_restores_the_original_gateway(gateway, monkeypatch, failure):
    folder, original, calls = gateway
    fail_once = True

    def command(args):
        nonlocal fail_once
        calls.append(args)
        should_fail = ('validate' in args if failure == 'validate' else args[0] == 'curl' if failure == 'https' else args[:2] == ['docker', 'compose'])
        if should_fail and fail_once:
            fail_once = False
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(access, 'run', command)
    with pytest.raises(subprocess.CalledProcessError):
        access.configure(folder, apply=True)
    assert (folder / 'Caddyfile').read_text(encoding='utf-8') == original


def test_public_update_package_has_verified_tools_and_no_credentials(tmp_path, monkeypatch):
    from cloud_deployment import build_frontend_update as builder
    root = tmp_path / 'source'
    (root / 'frontend/dist').mkdir(parents=True)
    (root / 'frontend/dist/index.html').write_text('frontend fixture', encoding='utf-8')
    (root / 'cloud_deployment').mkdir()
    for name in ['update_frontend.py', 'apply_server_update.py', 'configure_public_access.py', 'FRONTEND_UPDATE.md']:
        (root / 'cloud_deployment' / name).write_text('# tool fixture', encoding='utf-8')
    monkeypatch.setattr(builder, 'ROOT', root)
    destination = builder.build('public-access-test', public_access=True)
    with zipfile.ZipFile(destination) as archive:
        meta = json.loads(archive.read('frontend_update.json'))
        assert meta['website_access'] == 'public'
        assert set(meta['tools']) == {'update_frontend.py', 'apply_server_update.py', 'configure_public_access.py', 'FRONTEND_UPDATE.md'}
        for name, digest in meta['tools'].items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == digest
        assert not any(name.endswith(('users.caddy', '.key', '.pem')) for name in archive.namelist())


def test_combined_installer_stops_before_mutation_when_training_is_active(tmp_path, monkeypatch):
    from cloud_deployment import apply_server_update as installer
    tools = {name: hashlib.sha256(b'tool').hexdigest() for name in ['apply_server_update.py', 'configure_public_access.py', 'update_frontend.py', 'FRONTEND_UPDATE.md']}
    for name in tools:
        (tmp_path / name).write_bytes(b'tool')
    (tmp_path / 'frontend_update.json').write_text(json.dumps({'website_access': 'public', 'tools': tools}), encoding='utf-8')
    calls = []
    monkeypatch.setattr(installer, 'apply_update', lambda *a, **k: calls.append((a, k)) or {'dry_run': True})
    monkeypatch.setattr(installer, 'read_api', lambda path: {'items': [{'status': 'running'}]})
    with pytest.raises(ValueError, match='未结束实验'):
        installer.install(tmp_path, tmp_path / 'release', apply=True)
    assert len(calls) == 1 and len(calls[0][0]) == 2  # only the read-only frontend validation


@pytest.mark.parametrize('failure', ['build', 'gateway', None])
def test_combined_install_preserves_order_and_recovers_frontend_on_failure(tmp_path, monkeypatch, failure):
    from cloud_deployment import apply_server_update as installer
    tools = {name: hashlib.sha256(b'tool').hexdigest() for name in ['apply_server_update.py', 'configure_public_access.py', 'update_frontend.py', 'FRONTEND_UPDATE.md']}
    for name in tools:
        (tmp_path / name).write_bytes(b'tool')
    (tmp_path / 'frontend_update.json').write_text(json.dumps({'website_access': 'public', 'tools': tools}), encoding='utf-8')
    calls = []

    def frontend(*args, **kwargs):
        calls.append('frontend-apply' if kwargs.get('apply') else 'frontend-check')
        return {'backup': str(tmp_path / 'backup')}

    def gateway(*args, **kwargs):
        calls.append('gateway-apply' if kwargs.get('apply') else 'gateway-check')
        if kwargs.get('apply') and failure == 'gateway':
            raise RuntimeError('gateway fixture failure')
        return {'website_login_required': False}

    def command(args):
        calls.append('docker-build' if 'build' in args else 'docker-up')
        if failure == 'build' and calls.count('docker-build') == 1:
            raise RuntimeError('build fixture failure')

    monkeypatch.setattr(installer, 'apply_update', frontend)
    monkeypatch.setattr(installer, 'read_api', lambda path: {'items': []})
    monkeypatch.setattr(installer, 'configure', gateway)
    monkeypatch.setattr(installer, 'run', command)
    monkeypatch.setattr(installer, 'wait_ready', lambda: calls.append('ready'))
    monkeypatch.setattr(installer, 'rollback', lambda *args: calls.append('frontend-rollback'))
    if failure:
        with pytest.raises(RuntimeError, match='已恢复旧前端'):
            installer.install(tmp_path, tmp_path / 'release', apply=True)
        assert calls[-4:] == ['frontend-rollback', 'docker-build', 'docker-up', 'ready']
    else:
        result = installer.install(tmp_path, tmp_path / 'release', apply=True)
        assert result['website_login_required'] is False
        assert calls == ['frontend-check', 'gateway-check', 'frontend-apply', 'docker-build', 'docker-up', 'ready', 'gateway-apply']
