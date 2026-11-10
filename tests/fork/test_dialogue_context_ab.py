# SPDX-License-Identifier: AGPL-3.0-only
from copy import deepcopy
from tests.fork.dialogue_context_ab import BOUNDARY, STANDING, separate_card_context

TASK = BOUNDARY + '\nVerified facts: unchanged.\nTask: unchanged brief.'
SYSTEM = {'role': 'system', 'content': 'Native identity and all hardware protections.'}


def test_role_only_preserves_all_content_and_input_objects():
    prefix = 'EARLIER, THE PARTICIPANT SAID (already answered):\n- "Name a boat."\n\n'
    before = [SYSTEM, {'role':'user', 'content':prefix+TASK}]
    snapshot = deepcopy(before)
    after = separate_card_context(before)
    assert before == snapshot
    assert after == [SYSTEM, {'role':'assistant','content':prefix}, {'role':'user','content':TASK}]
    assert ''.join(m['content'] for m in after) == ''.join(m['content'] for m in before)


def test_story_context_is_moved_without_deletion_or_system_promotion():
    prefix = 'Story details from your conversation with the participant (fiction, possibly imperfect, not session facts):\n- A fictional café.\n\n'
    after = separate_card_context([SYSTEM, {'role':'user','content':prefix+TASK}])
    assert after[0] == SYSTEM and after[1]['role'] == 'assistant'
    assert after[1]['content'] == prefix and after[-1]['content'] == TASK


def test_standing_preferences_remain_user_instructions():
    standing = STANDING + '- "Always use plain language."\n\n'
    history = 'EARLIER, THE PARTICIPANT SAID (already answered):\n- "Name a boat."\n\n'
    after = separate_card_context([SYSTEM, {'role':'user','content':standing+history+TASK}])
    assert after[-1] == {'role':'user','content':standing+TASK}
    assert after[1] == {'role':'assistant','content':history}


def test_direct_user_requests_and_no_history_controls_are_unchanged():
    for content in ('What did I say earlier?', TASK, STANDING+'- "Never use pet names."\n\n'+TASK):
        before = [SYSTEM, {'role':'user','content':content}]
        assert separate_card_context(before) == before


def test_compiler_background_is_not_rewritten_into_stored_history():
    history = [{'role':'user','content':'A genuine earlier request.'}]
    before = [SYSTEM, *history, {'role':'user','content':'Past context.\n\n'+TASK}]
    after = separate_card_context(before)
    assert after[1] == history[0]
    assert after[0] == SYSTEM and after[-1]['content'] == TASK
