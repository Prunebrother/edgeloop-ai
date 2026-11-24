# SPDX-License-Identifier: AGPL-3.0-only
"""HELIX-022: chapter intro scenes (data, state, saved "seen", on-demand text) and the chapter close replay."""
import json
import pytest
from companion_ai.campaign import Book, Narrative, PROGRESS_FILE
from ai_observer.protocol import CampaignCommand
from tests.ai.test_campaign import CID, service
from tests.ai.test_campaign_chapter2 import seed

HID = 'rise_of_helix'


def chapter(svc, cid, number):
    return next(ch for c in svc.state()['campaigns'] if c['id'] == cid for ch in c['chapters'] if ch['number'] == number)


def test_shipped_helix_chapter_one_has_an_intro_and_teaser_none():
    n = Book.load().narratives[HID]
    assert set(n.chapter_intros) == {'undercover'} and 1 <= len(n.chapter_intros['undercover']) <= 8
    assert n.chapter_intros['undercover'][0].image == 'chapter_1_splash'


@pytest.mark.parametrize('change,error', [
    (lambda n: n.update(chapter_intros={'nope': [{'speaker': 'nova', 'lines': ['x']}]}), 'unknown or teaser'),
    (lambda n: n.update(chapter_intros={'helix_ch2': [{'speaker': 'nova', 'lines': ['x']}]}), 'unknown or teaser'),
    (lambda n: n.update(chapter_intros={'undercover': []}), '1 to 8'),
    (lambda n: n.update(chapter_intros={'undercover': [{'speaker': 'nova', 'lines': ['x'], 'image': 'env_lab'}]}), 'cannot use'),
])
def test_invalid_intros_reject_the_campaign(tmp_path, change, error):
    import shutil
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    for cid in (CID, HID): shutil.copytree(root / 'config/campaigns' / cid, tmp_path / cid)
    path = tmp_path / HID / 'narrative.json'; data = json.loads(path.read_text()); change(data); path.write_text(json.dumps(data))
    book = Book.load(tmp_path)
    assert [e['path'] for e in book.errors] == [HID] and error in book.errors[0]['detail']


def test_locked_chapter_has_no_text_then_intro_plays_once_and_is_saved(tmp_path):
    svc = service(tmp_path)
    with pytest.raises(ValueError, match='locked'): svc.chapter_text(HID, 'undercover')
    seed(tmp_path, None); svc = service(tmp_path)
    ch = chapter(svc, HID, 1)
    assert ch['intro'] and not ch['intro_seen'] and not ch['close']
    text = svc.chapter_text(HID, 'undercover')
    assert text['type'] == 'chapter_text' and len(text['intro']) == 2 and text['close'] is None
    assert text['narrative_status'] == 'placeholder'
    svc.intro_seen(HID, 'undercover'); svc.intro_seen(HID, 'undercover')  # idempotent
    saved = json.loads((tmp_path / PROGRESS_FILE).read_text())['campaigns'][HID]['intros_seen']
    assert list(saved) == ['undercover']
    assert chapter(service(tmp_path), HID, 1)['intro_seen']
    assert service(tmp_path).chapter_text(HID, 'undercover')['intro']  # still replayable from the board


def test_chapter_without_intro_and_teaser(tmp_path):
    seed(tmp_path, None); svc = service(tmp_path)
    assert not chapter(svc, CID, 1)['intro']
    with pytest.raises(ValueError, match='no intro'): svc.intro_seen(CID, 'introduction')
    with pytest.raises(ValueError, match='Unknown chapter'): svc.chapter_text(HID, 'helix_ch2')


def test_completed_chapter_close_is_replayable(tmp_path):
    fresh = service(tmp_path / 'fresh')
    assert not chapter(fresh, CID, 1)['close']
    assert fresh.chapter_text(CID, 'introduction')['close'] is None  # no spoiler before completion
    seed(tmp_path, None); svc = service(tmp_path)
    assert 'introduction' in svc.record(CID).chapters
    close = svc.book.narratives[CID].chapters['introduction']
    assert chapter(svc, CID, 1)['close']
    assert svc.chapter_text(CID, 'introduction')['close'] == close.model_dump(exclude_none=True)


def test_v4_save_without_intros_seen_loads(tmp_path):
    seed(tmp_path, None)
    data = json.loads((tmp_path / PROGRESS_FILE).read_text())
    assert all('intros_seen' not in r for r in data['campaigns'].values())
    svc = service(tmp_path)
    assert not svc.error and not chapter(svc, HID, 1)['intro_seen']


@pytest.mark.parametrize('raw,ok', [
    ({'action': 'chapter_text', 'campaign_id': HID, 'chapter_id': 'undercover'}, True),
    ({'action': 'intro_seen', 'campaign_id': HID, 'chapter_id': 'undercover'}, True),
    ({'action': 'chapter_text', 'campaign_id': HID}, False),
    ({'action': 'mission_text', 'campaign_id': HID, 'mission_id': 'h1_entry_protocol', 'chapter_id': 'undercover'}, False),
    ({'action': 'intro_seen', 'campaign_id': HID, 'chapter_id': '../x'}, False),
])
def test_protocol(raw, ok):
    from pydantic import ValidationError
    try: CampaignCommand.model_validate({'version': 1, 'type': 'campaign'} | raw); valid = True
    except ValidationError: valid = False
    assert valid == ok
