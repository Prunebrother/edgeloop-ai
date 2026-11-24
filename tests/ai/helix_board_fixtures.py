# SPDX-License-Identifier: AGPL-3.0-only
"""Small browser-only branch fixtures; shipped campaign files and source Book stay unchanged."""
from copy import deepcopy
from companion_ai.campaign import Book, Campaign, Narrative, Objective

BID = 'fixture_helix_board'


def book_with_board_fixtures(source=None):
    source = deepcopy(source or Book.load())
    # Keep the real completion/unlock path, reducing only the final Asterion mission's evidence for this fixture.
    asterion = source.campaign('asterion_initiative'); final = max(asterion.missions, key=lambda m: m.order)
    final.objectives = [o for o in final.objectives if o.type in {'hr_monitor_connected', 'toy_connected', 'session_started'}]
    final.objectives.append(Objective(id='fixture_finish', type='edge_count', label='Fixture finish', count=1))
    setup = [{'id': 'hr', 'type': 'hr_monitor_connected', 'label': 'Connect monitor'},
             {'id': 'toy', 'type': 'toy_connected', 'label': 'Connect toy'},
             {'id': 'start', 'type': 'session_started', 'label': 'Start fixture session'}]
    def mission(mid, order, **extra):
        return {'id': mid, 'order': order, 'title': mid.replace('_', ' ').title(), 'summary': 'Fixture mission', 'companion': 'nova',
                'objectives': deepcopy(setup) + [{'id': 'edges', 'type': 'edge_count', 'label': 'Keep fixture active', 'count': 99}], **extra}
    floor = mission('floor_path', 2)
    floor['objectives'] += [
        {'id': 'ladder', 'type': 'stage_sequence', 'label': 'Fixture floor ladder', 'stages': [
            {'id': 'low', 'label': 'Floor baseline', 'seconds': 10, 'set_to': True, 'raise_to': 80},
            {'id': 'high', 'label': 'Floor escalation', 'seconds': 10, 'set_to': True, 'raise_to': 110}]},
        {'id': 'bonus', 'type': 'orgasm_count', 'label': 'Fixture bonus sample', 'count': 1, 'optional': True,
            'when': {'flag': 'bonus', 'eq': 'shown'}},
        {'id': 'cover', 'type': 'choice', 'label': 'Choose fixture cover', 'choice': {'prompt': 'Which fixture cover?', 'options': [
            {'id': 'shown', 'label': 'Show bonus', 'sets': {'bonus': 'shown'}},
            {'id': 'hidden', 'label': 'Hide bonus', 'sets': {'bonus': 'hidden'}}]}}]
    campaign = Campaign.model_validate({'schema_version': 1, 'id': BID, 'order': 99, 'title': 'Helix board fixture',
        'description': 'Fixture for conditions and banner coverage', 'starting_companions': ['nova'], 'missions': [
            mission('entry', 1, flags={'access': 'blocked'}), floor,
            mission('locked_path', 3, when={'flag': 'access', 'eq': 'allowed'}, flags={'access': 'allowed'}, locked_reason='An analyst must vouch for you.'),
            mission('generic_path', 4, when={'flag': 'access', 'eq': 'allowed'})]})
    block = lambda text: {'speaker': 'nova', 'lines': [text]}
    narrative = Narrative.model_validate({'schema_version': 1, 'campaign': BID, 'status': 'approved', 'missions': {
        m.id: {'briefing': block('Fixture briefing.'), 'completion': block('Fixture complete.')} for m in campaign.missions}})
    return Book([*source.campaigns, campaign], source.narratives | {BID: narrative}, source.errors)
