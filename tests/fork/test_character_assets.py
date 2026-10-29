# SPDX-License-Identifier: AGPL-3.0-only
import importlib.util
import json
from pathlib import Path
import time
import pytest
from uuid import uuid4
from fastapi.testclient import TestClient
from ai_observer.server import create_app
from tests.fork.test_observer import TOKEN,ORIGIN,auth,until,frame,snapshot

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('f24_static',ROOT/'tools/serve_local.py')
static=importlib.util.module_from_spec(spec);spec.loader.exec_module(static)

def test_curated_artwork_references_are_public_but_archive_and_private_files_are_not():
    catalog=json.loads((ROOT/'src/assets/characters/manifest.json').read_text())
    assert static.public_file('/src/assets/characters/manifest.json')
    for character in catalog['characters'].values():
        for source in character['expressions'].values():
            if source:
                p=static.public_file(source)
                assert p and p.read_bytes()[:8]==b'\x89PNG\r\n\x1a\n'
    for path in ['/Character_Art/README.md','/Character_Art/Daisy/Daisy_Milk.png','/Character_Art/',
                 '/Character_Art/Daisy/expressions/../../../../.git/config','/config/ai.toml','/.ai-data/selection.json']:
        assert static.public_file(path) is None

def test_new_references_need_no_server_code_and_symlink_escape_stays_blocked(tmp_path):
    folder=tmp_path/'src/assets/characters';folder.mkdir(parents=True)
    art=tmp_path/'Character_Art';art.mkdir()
    outside=tmp_path/'secret.png';outside.write_bytes(b'not public')
    (art/'bad.png').symlink_to(outside)
    (art/'good.webp').write_bytes(b'fixture')
    (folder/'manifest.json').write_text(json.dumps({'characters':{'test':{'expressions':{'neutral':'/Character_Art/good.webp','excited':'/Character_Art/bad.png'}}}}))
    assert static.public_file('/Character_Art/good.webp',tmp_path)==art/'good.webp'
    assert static.public_file('/Character_Art/bad.png',tmp_path) is None

def test_presentation_ack_exposes_only_verified_deduplicated_source_events(tmp_path):
    app=create_app(TOKEN,tmp_path)
    with TestClient(app) as client:
        with client.websocket_connect('/observe',headers={'Origin':ORIGIN}) as ws:
            epoch=auth(ws)['epoch'];state=snapshot();event={'id':str(uuid4()),'kind':'edge'}
            ws.send_json(frame(epoch,state=state,events=[event]));ack=until(ws,'observation_ack')
            assert ack['accepted'] and ack['events']==[]
            time.sleep(.11);state['edges']+=1;event={'id':str(uuid4()),'kind':'edge'}
            ws.send_json(frame(epoch,1,state,[event]));ack=until(ws,'observation_ack')
            assert ack['events']==[event|{'session_id':state['session_id']}]
            time.sleep(.11);ws.send_json(frame(epoch,2,state,[event]));assert until(ws,'observation_ack')['events']==[]
