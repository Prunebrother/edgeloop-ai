"""Desktop credential boundary and service installation tests; no hardware."""
from functools import partial
from http.server import ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
from threading import Thread
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
import pytest

ROOT=Path(__file__).resolve().parents[2]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

@pytest.fixture
def pairing_server(tmp_path,monkeypatch):
    module=load('desktop_static','tools/serve_local.py')
    path=tmp_path/'pairing.json';path.write_text(json.dumps({'token':'x'*43,'url':'ws://127.0.0.1:8768/observe','browser_id':'a'*36}))
    monkeypatch.setenv('EDGELOOP_PAIRING_FILE',str(path))
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(module.Handler,directory=str(ROOT)))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield server,path
    finally:server.shutdown();server.server_close();thread.join()

def request(server,method='POST',origin=True,header=True,host=None):
    url=f'http://127.0.0.1:{server.server_port}'
    headers={}
    if origin:headers['Origin']=url if origin is True else origin
    if header:headers['X-EdgeLoop-Pair']='1'
    if host:headers['Host']=host
    return build_opener(ProxyHandler({})).open(Request(url+'/ai/pair',method=method,headers=headers))

def test_pairing_only_available_to_same_origin_post(pairing_server):
    server,path=pairing_server
    with request(server) as response:
        assert response.headers['Cache-Control']=='no-store'
        assert json.load(response)==json.loads(path.read_text())
    for kwargs,code in [({'method':'GET'},404),({'origin':False},403),({'origin':'https://example.com'},403),({'header':False},403),({'host':'attacker.test'},403)]:
        with pytest.raises(HTTPError) as exc:request(server,**kwargs)
        assert exc.value.code==code
    path.unlink()
    with pytest.raises(HTTPError) as exc:request(server)
    assert exc.value.code==503

def test_installer_has_one_target_and_no_login_enable(tmp_path,monkeypatch):
    module=load('desktop_install','tools/install_desktop.py')
    root=tmp_path/'repository';(root/'.venv/bin').mkdir(parents=True);(root/'.venv/bin/python').touch()
    monkeypatch.setattr(module.shutil,'which',lambda _: '/usr/bin/ollama')
    home=tmp_path/'home';module.install(root,home,reload=False)
    units=home/'.config/systemd/user'
    for name in ['ollama','observer','web']:
        text=(units/f'edgeloop-ai-{name}.service').read_text()
        assert 'PartOf=edgeloop-ai.target' in text
        assert 'KillMode=control-group' in text
        assert '[Install]' not in text
    assert 'RuntimeDirectoryMode=0700' in (units/'edgeloop-ai-observer.service').read_text()
    assert 'OLLAMA_MAX_LOADED_MODELS=1' in (units/'edgeloop-ai-ollama.service').read_text()
    assert (home/'.local/bin/edgeloop-ai').is_symlink()
    assert ' stop' in (home/'.local/share/applications/edgeloop-ai-stop.desktop').read_text()
    module.install(root,home,reload=False) # Idempotent reinstall.

@pytest.mark.parametrize('lifetime,accepted',[(3600,False),(float('inf'),True)])
def test_manual_key_expiry_and_managed_process_lifetime(tmp_path,lifetime,accepted):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from ai_observer.server import create_app
    from uuid import uuid4
    now=[0.0]
    app=create_app('x'*43,tmp_path,clock=lambda:now[0],pairing_lifetime=lifetime)
    now[0]=7200
    with TestClient(app) as client:
        if accepted:
            with client.websocket_connect('/observe',headers={'Origin':'http://127.0.0.1:8770'}) as ws:
                ws.send_json({'version':1,'type':'auth','token':'x'*43,'browser_id':str(uuid4())})
                assert ws.receive_json()['type']=='ready'
        else:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect('/observe',headers={'Origin':'http://127.0.0.1:8770'}) as ws:
                    ws.send_json({'version':1,'type':'auth','token':'x'*43,'browser_id':str(uuid4())})
                    ws.receive_json()


def test_optional_manual_fixture_pairing_without_desktop_file_returns_503(monkeypatch):
    from types import SimpleNamespace
    module=load('manual_fixture_static','tools/serve_local.py')
    handler=module.Handler.__new__(module.Handler)
    handler.path='/ai/pair';handler.server=SimpleNamespace(server_port=18950)
    handler.headers={'Host':'127.0.0.1:18950','Origin':'http://127.0.0.1:18950','X-EdgeLoop-Pair':'1'}
    errors=[];handler.send_error=errors.append
    monkeypatch.delenv('EDGELOOP_PAIRING_FILE',raising=False)
    handler.do_POST()
    assert errors==[503]
