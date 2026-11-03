"""Switch the existing password/TLS gateway to v2 while preserving credentials and certificates."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import subprocess
from urllib.request import urlopen
from cloud_deployment.public_gateway import public_ipv4,render_caddy,CADDY_IMAGE

def render(ip):
    return render_caddy(ip,training_enabled=True).replace(
        ' /api/v1/lab/tasks /api/v1/lab/tasks/*/cancel',
        ' /api/v1/lab/tasks /api/v1/lab/tasks/*/cancel /api/v1/experiments /api/v1/experiments/*/cancel /api/v1/datasets/import'
    ).replace('reverse_proxy 127.0.0.1:8080','reverse_proxy 127.0.0.1:18080').replace(
        'max_size 6MB','max_size 101MB').replace('read_body 30s','read_body 120s').replace(
        'Only frozen inference is enabled.','Unsupported operation.')

def run(args):
    subprocess.run(args,check=True)

def activate(ip,directory):
    directory=Path(directory).resolve()
    for name in ['Caddyfile','users.caddy','compose.gateway.json']:
        if not (directory/name).is_file() or (directory/name).is_symlink():
            raise ValueError(f'缺少原网关文件：{name}；不创建或替换密码')
    health=json.load(urlopen('http://127.0.0.1:18080/api/v1/health',timeout=30))
    datasets=json.load(urlopen('http://127.0.0.1:18080/api/v1/datasets',timeout=30))['items']
    if not health['data']['model_available'] or len(datasets)!=4 or any(d['status']!='ready' for d in datasets):
        raise ValueError('新服务尚未就绪，保持旧网关')
    candidate=directory/'Caddyfile.genescope2.candidate'
    candidate.write_text(render(ip),encoding='utf-8')
    run(['docker','run','--rm','--network','none','--read-only','--tmpfs','/tmp:rw,size=16m',
         '-e','XDG_CONFIG_HOME=/tmp/config','-e','XDG_DATA_HOME=/tmp/data',
         '-v',f'{candidate}:/etc/caddy/Caddyfile:ro','-v',f'{directory / "users.caddy"}:/etc/genescope/users.caddy:ro',
         CADDY_IMAGE,'caddy','validate','--config','/etc/caddy/Caddyfile','--adapter','caddyfile'])
    timestamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup=directory/f'Caddyfile.before-genescope2-{timestamp}'
    shutil.copyfile(directory/'Caddyfile',backup)
    shutil.copyfile(candidate,directory/'Caddyfile')
    command=['docker','compose','-f',str(directory/'compose.gateway.json'),'up','-d','--no-deps','--force-recreate','gateway']
    try:
        run(command)
    except Exception:
        shutil.copyfile(backup,directory/'Caddyfile')
        run(command)
        raise
    record={'previous_caddyfile':str(backup),'new_upstream':'127.0.0.1:18080','password_changed':False,'certificates_replaced':False}
    (directory/'genescope2_switch.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record,ensure_ascii=False,indent=2))

def rollback(directory):
    directory=Path(directory).resolve()
    record=json.loads((directory/'genescope2_switch.json').read_text(encoding='utf-8'))
    previous=Path(record['previous_caddyfile']).resolve()
    if previous.parent!=directory or not previous.name.startswith('Caddyfile.before-genescope2-') or not previous.is_file():
        raise ValueError('回滚记录无效')
    shutil.copyfile(previous,directory/'Caddyfile')
    run(['docker','compose','-f',str(directory/'compose.gateway.json'),'up','-d','--no-deps','--force-recreate','gateway'])

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['activate','rollback'])
    parser.add_argument('--ip',default='47.243.232.201',type=public_ipv4)
    parser.add_argument('--gateway-dir',type=Path,default=Path('/opt/genescope/gateway/20261102-ip-https'))
    args=parser.parse_args()
    activate(args.ip,args.gateway_dir) if args.action=='activate' else rollback(args.gateway_dir)
