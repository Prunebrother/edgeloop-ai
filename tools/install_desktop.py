"""AGPL-3.0-only. Install the desktop lifecycle without changing running services."""
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def install(root=ROOT,home=Path.home(),reload=True):
    if not (root/'.venv/bin/python').is_file():raise SystemExit('Run tools/setup-ai.sh first.')
    bundled=(root/'runtime/ollama/bin/ollama').is_file()
    ollama=str(root/'runtime/ollama/bin/ollama') if bundled else shutil.which('ollama')
    if not ollama:raise SystemExit('Install Ollama first. No models will be downloaded.')
    # systemd quoted values: escape specifiers as well as special characters.
    def quote(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    units=home/'.config/systemd/user';apps=home/'.local/share/applications';bin_dir=home/'.local/bin'
    for directory in (units,apps,bin_dir):directory.mkdir(parents=True,exist_ok=True)
    common='PartOf=edgeloop-ai.target\n'
    services={
        'ollama':('Dedicated EdgeLoop AI Ollama', '', f'''Environment="OLLAMA_HOST=127.0.0.1:11435"
Environment={quote('OLLAMA_MODELS='+str(root/'models' if bundled else home/'.ollama/models'))}
Environment="OLLAMA_NO_CLOUD=1"
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_FLASH_ATTENTION=1"
ExecStart={quote(ollama)} serve
'''),
        'observer':('EdgeLoop AI read-only observer','Requires=edgeloop-ai-ollama.service\nAfter=edgeloop-ai-ollama.service\n',f'''RuntimeDirectory=edgeloop-ai
RuntimeDirectoryMode=0700
UMask=0077
Environment="EDGELOOP_PAIRING_FILE=%t/edgeloop-ai/pairing.json"
Environment="EDGELOOP_OBSERVER_PORT=8768"
Environment="EDGELOOP_OLLAMA_URL=http://127.0.0.1:11435"
Environment={quote('EDGELOOP_FORK_AI_DATA='+str(home/'.local/share/edgeloop-ai/data'))}
ExecStart={quote(root/'tools/serve-ai.sh')}
'''),
        'web':('EdgeLoop AI web interface','Requires=edgeloop-ai-observer.service\nAfter=edgeloop-ai-observer.service\n',f'''Environment="EDGELOOP_PAIRING_FILE=%t/edgeloop-ai/pairing.json"
ExecStart={quote(root/'.venv/bin/python')} {quote(root/'tools/serve_local.py')} 8770
''')}
    for name,(description,dependencies,settings) in services.items():
        (units/f'edgeloop-ai-{name}.service').write_text(f'''[Unit]
Description={description}
{common}{dependencies}
[Service]
Type=simple
WorkingDirectory={str(root).replace('%','%%')}
{settings}KillMode=control-group
TimeoutStopSec=30
Restart=no
''')
    (units/'edgeloop-ai.target').write_text('''[Unit]
Description=EdgeLoop AI local stack
Requires=edgeloop-ai-ollama.service edgeloop-ai-observer.service edgeloop-ai-web.service
After=edgeloop-ai-ollama.service edgeloop-ai-observer.service edgeloop-ai-web.service
''')
    command=bin_dir/'edgeloop-ai'
    if command.is_symlink():command.unlink()
    elif command.exists():raise SystemExit(f'Refusing to overwrite existing {command}')
    command.symlink_to(root/'tools/launch-desktop.sh')
    # Desktop Exec quoting uses a separate grammar; escape reserved characters.
    def desktop_quote(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$').replace('%','%%')+'"'
    for filename,name,action,comment in [
        ('edgeloop-ai.desktop','EdgeLoop AI','start','Start local EdgeLoop AI and open its interface'),
        ('edgeloop-ai-stop.desktop','Stop EdgeLoop AI','stop','Stop the web server, AI observer and dedicated Ollama; end hardware sessions in EdgeLoop first')]:
        extra='Actions=Stop;\n' if action=='start' else ''
        text=f'''[Desktop Entry]
Type=Application
Name={name}
Comment={comment}
Exec={desktop_quote(command)} {action}
Icon={root/'icon-192.png'}
Terminal=false
Categories=Utility;
Keywords=EdgeLoop;AI;Ollama;Companion;
{extra}'''
        if action=='start':text+=f'\n[Desktop Action Stop]\nName=Stop EdgeLoop AI\nExec={desktop_quote(command)} stop\n'
        (apps/filename).write_text(text)
    if reload:
        subprocess.run(['systemctl','--user','daemon-reload'],check=True)
        if shutil.which('update-desktop-database'):subprocess.run(['update-desktop-database',str(apps)],check=True)
    print('Installed EdgeLoop AI and Stop EdgeLoop AI. No services started or enabled at login.')

if __name__=='__main__':install()
