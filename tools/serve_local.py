"""AGPL-3.0-only. Local static UI only: never serve AI memory, Git or Python."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
import sys
import os
import json
import re
from urllib.parse import unquote, urlsplit

ROOT=Path(__file__).resolve().parents[1]
PUBLIC={'index.html','sw.js','manifest.json','README.md','CHANGELOG.md','LICENSE','FORK_README.md','NOTICE_FORK.md'}

def public_file(raw, root=ROOT):
    path=unquote(urlsplit(raw).path).lstrip('/') or 'index.html'
    # Windows would read a backslash as a separator and a colon as a drive or stream name.
    if '\\' in path or ':' in path or '\0' in path: return None
    parts=PurePosixPath(path).parts
    if any(p.startswith('.') for p in parts): return None
    allowed=path in PUBLIC or (len(parts)==1 and parts[0].startswith('icon') and Path(path).suffix in {'.svg','.png'}) or (path.startswith('src/js/') and path.endswith('.js')) or (path.startswith('src/css/') and path.endswith('.css')) or (path.startswith('src/assets/characters/') and Path(path).suffix in {'.png','.webp','.jpg','.jpeg','.svg'})
    # Only curated references are public; never expose the artwork archive itself.
    if path=='src/assets/characters/manifest.json':allowed=True
    if path.startswith('Character_Art/'):
        try:
            catalog=json.loads((root/'src/assets/characters/manifest.json').read_text())
            referenced={asset.lstrip('/') for c in catalog['characters'].values() for asset in c['expressions'].values() if isinstance(asset,str)}
            animations={asset.lstrip('/') for c in catalog['characters'].values()
                        for expression,clips in c.get('animations',{}).items() if expression in catalog.get('expressions',[])
                        for fmt,asset in clips.items() if fmt in {'webm','mp4'} and isinstance(asset,str)
                        and re.fullmatch(r'/Character_Art/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.'+fmt,asset)}
            allowed=(path in referenced and Path(path).suffix.lower() in {'.png','.jpg','.jpeg','.webp'}) or path in animations
        except (OSError,ValueError,KeyError,TypeError,AttributeError):allowed=False
    target=root/path
    if target.absolute()!=target.resolve():return None
    if not allowed or target.is_symlink() or not target.resolve().is_relative_to(root.resolve()): return None
    if any(p.startswith('.') for p in target.resolve().relative_to(root.resolve()).parts):return None
    return target if target.is_file() else None

class Handler(SimpleHTTPRequestHandler):
    def do_POST(self):
        # Custom header + exact Origin and Host prevent cross-origin pairing and
        # DNS rebinding. Never expose credentials through GET or offline caches.
        expected=f'127.0.0.1:{self.server.server_port}'
        if (self.path!='/ai/pair' or self.headers.get('Host')!=expected or
                self.headers.get('Origin')!='http://'+expected or
                self.headers.get('X-EdgeLoop-Pair')!='1'):
            self.send_error(403);return
        path=os.environ.get('EDGELOOP_PAIRING_FILE')
        try:
            if not path:raise OSError()
            credentials=json.loads(Path(path).read_text())
            body=json.dumps(credentials).encode()
        except (OSError,ValueError):
            self.send_error(503);return
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(body)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers();self.wfile.write(body)

    def send_head(self):
        if public_file(self.path,Path(self.directory)) is None:
            self.send_error(404);return None
        return super().send_head()
    def list_directory(self,path):self.send_error(404);return None
    # Revalidate on every load (an unchanged file is a cheap 304). Without this the browser
    # may keep an old companion.css heuristically fresh next to a newer layout.js after an
    # update, and the dashboard loses its scroll containers.
    def send_header(self,keyword,value):
        if keyword.lower()=='cache-control':self._cache_control=True
        super().send_header(keyword,value)
    def end_headers(self):
        if not getattr(self,'_cache_control',False):self.send_header('Cache-Control','no-cache')
        self._cache_control=False
        super().end_headers()

if __name__=='__main__':
    try:
        port=int(sys.argv[1]) if len(sys.argv)>1 else 8770
        if not 1<=port<=65535:raise ValueError()
    except ValueError:
        raise SystemExit('UI port must be an integer between 1 and 65535')
    try:
        server_class=ThreadingHTTPServer
        if os.name=='nt':
            # On Windows SO_REUSEADDR would let two servers share the port. Claim it exclusively.
            class server_class(ThreadingHTTPServer):
                allow_reuse_address=False
                def server_bind(self):
                    import socket
                    self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
                    super().server_bind()
        server=server_class(('127.0.0.1',port),partial(Handler,directory=str(ROOT)))
    except OSError as exc:
        raise SystemExit(f'Cannot start EdgeLoop on 127.0.0.1:{port}: {exc.strerror}. Inspect ss -ltnp or choose another port. No process was stopped.')
    with server:
        print(f'Original EdgeLoop: http://127.0.0.1:{port}/ (AI optional)',flush=True)
        server.serve_forever()
