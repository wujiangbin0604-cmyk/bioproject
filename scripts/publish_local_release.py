"""发布已校验的本地客户端；凭据仅在内存使用，不写入日志或文件。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """认证请求不自动跟随重定向到其他主机。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def credential():
    """复用已授权GitHub登录；禁止把口令打印到终端。"""
    if os.getenv('GITHUB_TOKEN'):
        return os.environ['GITHUB_TOKEN']
    result = subprocess.run(['git', '-c', 'credential.username=wujiangbin0604-cmyk', 'credential', 'fill'],
                            input=b'protocol=https\nhost=github.com\nusername=wujiangbin0604-cmyk\n\n',
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            env={**os.environ, 'GCM_INTERACTIVE': 'Never'}, cwd=ROOT)
    values = dict(line.split('=', 1) for line in result.stdout.decode().splitlines() if '=' in line)
    if result.returncode or not values.get('password'):
        raise RuntimeError('现有Git登录不可用于GitHub API，请先完成GitHub/Git凭据登录')
    return values['password']


def checked_archive(path, commit):
    """只接受已提交源码构建、逐文件校验通过且不含运行数据的客户端。"""
    with zipfile.ZipFile(path) as archive:
        info = json.loads(archive.read('local_bundle_manifest.json'))
        if info.get('source_kind') != 'committed' or info.get('source_commit') != commit or info.get('raw_data_included') is not False or info.get('dynamic_models_included') is not False:
            raise ValueError('运行包来源或数据范围不符')
        if set(archive.namelist()) != set(info['files']) | {'local_bundle_manifest.json'}:
            raise ValueError('运行包存在清单外文件')
        for relative, expected in info['files'].items():
            if hashlib.sha256(archive.read(relative)).hexdigest() != expected:
                raise ValueError(f'运行包校验失败：{relative}')
    return info


def main():
    """先建立草稿并上传全部附件，核对摘要后才公开发布。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--notes', type=Path, required=True)
    parser.add_argument('--repo', default='wujiangbin0604-cmyk/bioproject')
    parser.add_argument('--proxy')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--update-metadata', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', args.repo):
        parser.error('仓库名无效')
    git = ['git', '-c', f'safe.directory={ROOT.as_posix()}']
    commit = subprocess.check_output(git + ['rev-parse', 'HEAD'], cwd=ROOT).decode().strip()
    info = checked_archive(args.archive, commit)
    tag = 'v' + info['version']
    checksum_file = args.archive.with_suffix('.zip.sha256')
    if checksum_file.read_text().split()[0] != hashlib.sha256(args.archive.read_bytes()).hexdigest():
        raise ValueError('ZIP外部校验文件不匹配')
    token = credential()
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.ProxyHandler({'https': args.proxy} if args.proxy else {}))

    def request(url, method='GET', data=None, binary=None):
        if urllib.parse.urlparse(url).hostname not in {'api.github.com', 'uploads.github.com'}:
            raise ValueError('拒绝向非GitHub API主机发送凭据')
        payload = binary if binary is not None else json.dumps(data, ensure_ascii=False).encode() if data is not None else None
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
                   'X-GitHub-Api-Version': '2026-03-10', 'User-Agent': 'GeneScope-local-release',
                   'Content-Type': 'application/octet-stream' if binary is not None else 'application/json'}
        try:
            with opener.open(urllib.request.Request(url, data=payload, headers=headers, method=method), timeout=180) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404 and method == 'GET':
                return None
            raise RuntimeError(f'GitHub API返回HTTP {error.code}；凭据内容未输出') from None

    api = 'https://api.github.com/repos/' + args.repo
    if not request(api + '/commits/' + commit):
        raise ValueError('提交尚未推送到目标仓库')
    release = request(api + '/releases/tags/' + urllib.parse.quote(tag, safe=''))
    if release and release['target_commitish'] != commit:
        raise ValueError('同名发布指向其他提交，拒绝覆盖')
    if not release:
        release = request(api + '/releases', 'POST', {'tag_name': tag, 'target_commitish': commit,
                          'name': 'GeneScope ' + info['version'] + ' · 本地运行包',
                          'body': args.notes.read_text(encoding='utf-8'), 'draft': True, 'prerelease': False})
    assets = {asset['name']: asset for asset in release.get('assets', [])}
    for path in [args.archive, checksum_file]:
        data = path.read_bytes(); expected = 'sha256:' + hashlib.sha256(data).hexdigest()
        if path.name in assets:
            asset = assets[path.name]
        else:
            if not release['draft']:
                raise ValueError('不修改已公开发布的附件')
            upload = release['upload_url'].split('{')[0] + '?name=' + urllib.parse.quote(path.name)
            asset = request(upload, 'POST', binary=data)
            assets[path.name] = asset
        if asset['size'] != len(data) or asset.get('digest') not in {None, expected}:
            raise ValueError('GitHub附件大小或摘要不同，保留草稿并停止')
    if args.publish and release['draft']:
        release = request(api + '/releases/' + str(release['id']), 'PATCH', {'draft': False, 'make_latest': 'true'})
    metadata = 'unchanged'
    if args.update_metadata:
        request(api, 'PATCH', {'description': 'GeneScope 2.0：可本地运行的基因表达分析、真实机器学习实验与模型预测平台。',
                              'homepage': 'https://github.com/' + args.repo + '/releases/latest'})
        existing = request(api + '/topics') or {}
        topics = list(dict.fromkeys(existing.get('names', []) + ['bioinformatics','gene-expression','machine-learning','fastapi','react','local-first']))[:20]
        request(api + '/topics', 'PUT', {'names': topics})
        metadata = 'updated'
    print(json.dumps({'release': release['html_url'], 'draft': release['draft'], 'source_commit': commit,
                      'metadata': metadata, 'assets': [{'name': a['name'], 'url': a['browser_download_url'], 'bytes': a['size'], 'digest': a.get('digest')} for a in assets.values()]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
