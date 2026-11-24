# SPDX-License-Identifier: AGPL-3.0-only
"""Pure editorial lint and release gate; authored fixtures never alter shipped campaign content."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from companion_ai.campaign import Book, Campaign, Narrative, NarrativeBlock, When
from companion_ai.narrative_lint import Finding, REAL_CONTROL_CLAIMS, lint
from tests.ai.test_campaign_when import CID, definition, narrative, block

ROOT = Path(__file__).resolve().parents[2]


def inputs():
    text = narrative(); text['missions']['intake']['briefing'].update(image='arrival', background='room', expression='happy')
    return (Book([Campaign.model_validate(definition())], {CID: Narrative.model_validate(text)}),
        {'characters': {'nova': {}}}, {CID: {'campaign': CID, 'slots': {'arrival': {'kind': 'illustration'}, 'room': {'kind': 'environment'}}}})


def test_shipped_book_has_no_lint_errors():
    book = Book.load(); manifest = json.loads((ROOT / 'src/assets/characters/manifest.json').read_text())
    registries = {path.parent.name: json.loads(path.read_text()) for path in (ROOT / 'src/assets/story').glob('*/ASSETS.json')}
    findings = lint(book, manifest, registries)
    for finding in findings:
        if finding.severity != 'error': print(json.dumps(finding._asdict(), ensure_ascii=False))
    assert not [finding for finding in findings if finding.severity == 'error']


def test_lint_is_pure_and_does_not_open_files_or_change_inputs(monkeypatch):
    book, manifest, registries = inputs(); before = deepcopy((book.campaigns, book.narratives, manifest, registries))
    monkeypatch.setattr(Path, 'read_text', lambda *a, **k: pytest.fail('Lint tried to open a file'))
    assert not any(f.severity == 'error' for f in lint(book, manifest, registries))
    assert (book.campaigns, book.narratives, manifest, registries) == before


@pytest.mark.parametrize('location', ['briefing', 'completion', 'epilogue', 'milestone', 'intro', 'close', 'campaign_complete'])
def test_unknown_speakers_have_exact_locations(location):
    book, manifest, registries = inputs(); n = book.narratives[CID]; m = n.missions['intake']
    target = {'briefing': m.briefing, 'completion': m.completion, 'epilogue': m.epilogue[0],
        'milestone': m.milestones['edges:done'], 'intro': n.chapter_intros['one'][0], 'close': n.chapters['one']}.get(location)
    if location == 'campaign_complete': n.campaign_complete = NarrativeBlock.model_validate(block('Final')); target = n.campaign_complete
    target.speaker = 'missing'
    finding = next(f for f in lint(book, manifest, registries) if 'unknown narrative speaker' in f.message)
    expected = {'briefing': 'missions.intake.briefing', 'completion': 'missions.intake.completion',
        'epilogue': 'missions.intake.epilogue[0]', 'milestone': 'missions.intake.milestones.edges:done',
        'intro': 'chapter_intros.one[0]', 'close': 'chapters.one', 'campaign_complete': 'campaign_complete'}[location]
    assert finding == Finding('error', CID, expected + '.speaker', 'unknown narrative speaker missing')


def test_expression_check_locates_a_value_that_bypassed_model_validation():
    book, manifest, registries = inputs()
    # Normal definitions reject this already; copy-with-update represents an editor's partially validated draft.
    n = book.narratives[CID]; n.missions['intake'].briefing = n.missions['intake'].briefing.model_copy(update={'expression': 'unknown'})
    assert Finding('error', CID, 'missions.intake.briefing.expression', 'unknown expression unknown') in lint(book, manifest, registries)


@pytest.mark.parametrize('site', ['mission', 'objective', 'block', 'history'])
@pytest.mark.parametrize('condition', [{'flag': 'unknown', 'eq': 'analyst'}, {'flag': 'cover', 'eq': 'unknown'}])
def test_unknown_flag_or_value_at_each_condition_site(site, condition):
    book, manifest, registries = inputs(); campaign = book.campaign(CID); mission = campaign.missions[0]
    when = When.model_validate(condition)
    if site == 'mission': mission.when = when; location = 'missions.intake.when'
    elif site == 'objective': mission.objectives[-1].when = when; location = 'missions.intake.objectives.bonus.when'
    elif site == 'block': book.narratives[CID].missions['intake'].briefing.when = when; location = 'missions.intake.briefing.when'
    else:
        from companion_ai.campaign import StorySoFar
        book.narratives[CID].missions['intake'].story_so_far = [StorySoFar(when=when, text='Private history')]
        location = 'missions.intake.story_so_far[0].when'
    assert any(f.severity == 'error' and f.location == location for f in lint(book, manifest, registries))


def test_inherited_conditions_and_route_declarations_are_accepted():
    from tests.ai.test_campaign_routes import definition as route_definition
    book, manifest, registries = inputs(); source = Campaign.model_validate(route_definition()).model_copy(update={'id': 'source'})
    book.campaigns.append(source)
    campaign = book.campaign(CID); campaign.inherits_flags_from = ['source']
    campaign.missions[0].when = When(flag='source.route', eq='escape')
    assert not any(f.severity == 'error' for f in lint(book, manifest, registries))


@pytest.mark.parametrize('field,value,kind', [('image', 'missing', None), ('background', 'arrival', 'illustration'), ('image', 'room', 'environment')])
def test_bad_art_slot_reports_field_and_kind(field, value, kind):
    book, manifest, registries = inputs(); setattr(book.narratives[CID].missions['intake'].briefing, field, value)
    finding = next(f for f in lint(book, manifest, registries) if f.location == 'missions.intake.briefing.' + field)
    assert finding.severity == 'error' and (kind in finding.message if kind else 'unknown story-art slot' in finding.message)


def test_absent_registry_and_both_bad_fields_are_reported():
    book, manifest, registries = inputs(); findings = lint(book, manifest, {})
    assert {f.location for f in findings if 'no story-art registry' in f.message} == {'missions.intake.briefing.image', 'missions.intake.briefing.background'}


@pytest.mark.parametrize('value', ['placeholder', 'draft'])
@pytest.mark.parametrize('where', ['narrative', 'block'])
def test_review_status_warning_becomes_release_error(value, where):
    book, manifest, registries = inputs(); n = book.narratives[CID]
    if where == 'narrative': n.status = value; location = 'status'
    else: n.missions['intake'].briefing.status = value; location = 'missions.intake.briefing.status'
    assert Finding('warning', CID, location, value + ' campaign narrative') in lint(book, manifest, registries)
    assert Finding('error', CID, location, value + ' campaign narrative') in lint(book, manifest, registries, release=True)


@pytest.mark.parametrize('phrase', REAL_CONTROL_CLAIMS)
def test_control_claims_are_review_only_including_release_mode(phrase):
    book, manifest, registries = inputs(); n = book.narratives[CID]
    n.chapter_intros = {}; n.missions['intake'].briefing.lines = [phrase.upper().replace("'", '\u2019') + '.']
    n.missions['intake'].directions = {'start': 'She says: ' + phrase + '.'}
    findings = lint(book, manifest, registries, release=True)
    assert not any(f.severity == 'error' for f in findings)
    hits = [f for f in findings if f.severity == 'review']
    assert {f.location for f in hits} == {'missions.intake.briefing.lines[0]', 'missions.intake.directions.start'}


def test_claim_matching_uses_word_boundaries_and_reports_each_hit():
    book, manifest, registries = inputs(); n = book.narratives[CID]
    n.missions['intake'].briefing.lines = ["I'll turn it upside down. I've set theme music. You can't stopper.", "I'll turn it up. I'll turn it up."]
    hits = [f for f in lint(book, manifest, registries) if f.severity == 'review']
    assert len(hits) == 2 and all(f.location == 'missions.intake.briefing.lines[1]' for f in hits)
    assert hits[0].message != hits[1].message


def test_book_load_errors_are_never_silently_dropped():
    book, manifest, registries = inputs(); book.errors.append({'path': 'broken', 'detail': 'Invalid condition'})
    assert Finding('error', 'broken', 'campaign.json', 'Invalid condition') in lint(book, manifest, registries)


def release_fixture(tmp_path, *, status='approved', speaker='test', line='A fixture line.'):
    from tests.fork.test_story_art import release_tree, inventory, load
    path, catalog = release_tree(tmp_path)
    folder = tmp_path / 'config/campaigns' / CID; folder.mkdir(parents=True)
    data = definition(); data['starting_companions'] = ['test']; data['missions'][0]['companion'] = 'test'
    text = {'schema_version': 1, 'campaign': CID, 'status': status, 'missions': {'intake': {
        'briefing': block(line, speaker=speaker), 'completion': block('Done', speaker='test')}}}
    (folder / 'campaign.json').write_text(json.dumps(data)); (folder / 'narrative.json').write_text(json.dumps(text))
    inventory(tmp_path); module = load('validate-release'); module.ROOT = tmp_path
    return module


@pytest.mark.parametrize('status', ['placeholder', 'draft'])
def test_release_validator_delegates_status_and_preserves_placeholder_message(tmp_path, status):
    result = release_fixture(tmp_path, status=status).validate()
    assert not result['passed'] and any(f['severity'] == 'error' and f['location'] == 'status' for f in result['narrative_findings'])
    if status == 'placeholder': assert {'path': CID, 'category': 'placeholder campaign narrative'} in result['errors']


def test_release_validator_refuses_unknown_speaker_but_only_reports_control_claims(tmp_path):
    module = release_fixture(tmp_path, speaker='unknown'); result = module.validate()
    assert not result['passed'] and any('unknown narrative speaker' in e['category'] for e in result['errors'])
    file = tmp_path / 'config/campaigns' / CID / 'narrative.json'; text = json.loads(file.read_text())
    text['missions']['intake']['briefing'].update(speaker='test', lines=["I'll turn it up."])
    file.write_text(json.dumps(text))
    from tests.fork.test_story_art import inventory
    inventory(tmp_path); result = module.validate()
    assert result['passed'] and any(f['severity'] == 'review' for f in result['narrative_findings'])
