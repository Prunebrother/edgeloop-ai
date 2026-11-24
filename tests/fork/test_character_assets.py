# SPDX-License-Identifier: AGPL-3.0-only
import importlib.util
import json
from pathlib import Path
import time
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

def test_menu_art_is_public_and_only_its_curated_file_types():
    for path in ['/src/assets/menu/backdrop.webp','/src/assets/menu/mark.svg','/src/assets/menu/wordmark.svg',
                 '/src/assets/menu/fonts/cormorant-garamond-600.woff2','/src/assets/menu/companions/mira.webp',
                 '/src/assets/menu/campaigns/asterion_initiative/chapter-3.webp']:
        assert static.public_file(path), path
    for path in ['/src/assets/menu/../../../.git/config','/src/assets/menu/readme.md','/src/assets/menu/x.png','/src/assets/menu/.hidden.webp']:
        assert static.public_file(path) is None, path

def assert_menu_art_references(root):
    import re
    source=(root/'src/js/ai/menu-art.js').read_text()
    files=sorted(p.relative_to(root/'src/assets/menu').as_posix() for p in (root/'src/assets/menu').rglob('*') if p.is_file())
    for name in ['backdrop.webp','mark.svg','wordmark.svg','fonts/cormorant-garamond-600.woff2']:
        assert name in files
    for c in re.search(r"COMPANION_ORDER=Object.freeze\(\[([^\]]+)\]",source)[1].replace("'",'').split(','):
        assert f'companions/{c}.webp' in files and f'companions/{c}-face.webp' in files
    mapping=re.search(r'const CAMPAIGN_ART=({.*?})\s*;',source,re.S)[1]
    # The map is a data literal: quote its JS keys and strings for the stdlib JSON parser.
    mapping=re.sub(r'([{,]\s*)([A-Za-z0-9_-]+)\s*:',r'\1"\2":',mapping).replace("'",'"')
    mapping=re.sub(r',\s*([}\]])',r'\1',mapping)
    for campaign,art in json.loads(mapping).items():
        if art.get('story'):
            from tools.story_art import load_registry, validate
            folder=root/'src/assets/story'/campaign
            registry=validate(load_registry(folder/'ASSETS.json'),folder)
            assert registry['campaign']==campaign and 'key_art' in registry['slots']
            continue
        for name in [art['key'],*art['chapters'].values()]:
            assert f'campaigns/{campaign}/{name}' in files


def test_every_menu_art_reference_exists_on_disk():
    assert_menu_art_references(ROOT)


def test_menu_art_reference_check_detects_missing_campaign_file(tmp_path):
    import pytest
    menu=tmp_path/'src/assets/menu';menu.mkdir(parents=True)
    source=tmp_path/'src/js/ai/menu-art.js';source.parent.mkdir(parents=True)
    source.write_text("COMPANION_ORDER=Object.freeze(['test']);\nconst CAMPAIGN_ART={\n    another_campaign:{key:'missing.webp',chapters:{8:'eight.webp'}},\n};")
    for name in ['backdrop.webp','mark.svg','wordmark.svg','fonts/cormorant-garamond-600.woff2']:
        p=menu/name;p.parent.mkdir(parents=True,exist_ok=True);p.touch()
    (menu/'companions').mkdir()
    for name in ['test.webp','test-face.webp']:(menu/'companions'/name).touch()
    with pytest.raises(AssertionError):assert_menu_art_references(tmp_path)
    campaign=menu/'campaigns/another_campaign';campaign.mkdir(parents=True)
    (campaign/'missing.webp').touch()
    with pytest.raises(AssertionError):assert_menu_art_references(tmp_path)
    (campaign/'eight.webp').touch()
    assert_menu_art_references(tmp_path)


def test_story_campaign_art_reference_uses_and_validates_the_registry(tmp_path):
    from tests.fork.test_story_art import fixture
    import pytest
    # Reuse the ordinary menu-file fixture before adding a story-backed campaign.
    test_menu_art_reference_check_detects_missing_campaign_file(tmp_path)
    source=tmp_path/'src/js/ai/menu-art.js'
    source.write_text(source.read_text().replace('\n};','\n    test_campaign:{story:true},\n};'))
    folder,registry=fixture(tmp_path)
    with pytest.raises(AssertionError):assert_menu_art_references(tmp_path)  # No key-art slot.
    registry['slots']['key_art']=registry['slots'].pop('arrival')
    (folder/'ASSETS.json').write_text(json.dumps(registry))
    assert_menu_art_references(tmp_path)
    (folder/'arrival.webp').unlink()
    with pytest.raises(ValueError,match='missing file'):assert_menu_art_references(tmp_path)
