# SPDX-License-Identifier: AGPL-3.0-only
"""Real compiler boundary tests; all observations are synthetic."""
from copy import deepcopy
import hashlib
import json

import pytest

from companion_ai.context_compiler import ContextCompiler, ContextConfig
from companion_ai.models import AIConfig, MemoryConfig
from tests.fork.grounding_cases import cases

EARLIER = 'Pick Marigold or Tinfoil for a fictional paper boat.'
STANDING = 'Always use plain language.'
NARRATIVE = {'premise': 'A fictional café named Copper Teacup.',
             'choices': ['Choose Copper Teacup or Velvet Lantern.']}


def inputs(card=True):
    summary = cases()[1].summary()
    if card:
        summary |= {'conversation_source': 'event', 'deck_card': {
            'lane': 'normal', 'card_id': 'evelyn-research-ambition',
            'brief': 'Share a research ambition. No question.', 'memory': 'none'}}
    return summary


def compile(summary, history=(), policy='last_user', **limits):
    return ContextCompiler(ContextConfig(history_policy=policy, **limits)).compile(
        summary, 'Offer a fresh remark.' if summary.get('deck_card') else 'Tell me about music.',
        list(history), AIConfig(), MemoryConfig(max_messages=64))


@pytest.mark.parametrize('answer', [None, 'Marigold.'])
def test_answered_request_is_background_even_without_original_assistant_reply(answer):
    history = [{'role': 'user', 'content': EARLIER}]
    if answer:
        history.append({'role': 'assistant', 'content': answer})
    before = deepcopy(history)
    messages, _, _ = compile(inputs(), history)
    assert [m['role'] for m in messages] == ['system', 'assistant', 'user']
    assert EARLIER in messages[1]['content'] and 'already answered; background only' in messages[1]['content']
    assert EARLIER not in messages[-1]['content'] and 'Task: Share a research ambition.' in messages[-1]['content']
    assert history == before


def test_narrative_excerpts_and_raw_request_are_not_active_card_instructions():
    summary = inputs() | {'narrative_context': deepcopy(NARRATIVE)}
    before = deepcopy(summary)
    messages, _, _ = compile(summary, [{'role': 'user', 'content': EARLIER}])
    assert 'Copper Teacup' in messages[-2]['content'] and EARLIER in messages[-2]['content']
    assert 'fiction, possibly imperfect, not session facts' in messages[-2]['content']
    assert all(word not in messages[-1]['content'] for word in ('Teacup', 'Lantern', 'Tinfoil', 'Marigold'))
    assert summary == before


def test_narrative_alone_gets_a_separate_provenance_labelled_turn():
    messages, _, _ = compile(inputs() | {'narrative_context': deepcopy(NARRATIVE)})
    assert [m['role'] for m in messages] == ['system', 'assistant', 'user']
    assert 'Story details' in messages[1]['content'] and 'Copper Teacup' not in messages[-1]['content']


def test_standing_instruction_remains_active_without_promoting_old_request():
    history = [{'role': 'user', 'content': STANDING}, {'role': 'user', 'content': EARLIER}]
    messages, _, _ = compile(inputs(), history)
    assert STANDING in messages[-1]['content'] and 'STANDING INSTRUCTION' in messages[-1]['content']
    assert STANDING not in messages[-2]['content'] and EARLIER not in messages[-1]['content']


def test_standing_instruction_alone_adds_no_synthetic_context_turn():
    messages, _, _ = compile(inputs(), [{'role': 'user', 'content': STANDING}])
    assert [m['role'] for m in messages] == ['system', 'user']
    assert STANDING in messages[-1]['content']


def test_ranked_history_and_card_narrative_stay_outside_current_user_turn():
    messages, _, _ = compile(inputs() | {'narrative_context': deepcopy(NARRATIVE)},
                             [{'role': 'user', 'content': EARLIER}], policy='ranked')
    assert EARLIER in messages[1]['content'] and 'Copper Teacup' in messages[-2]['content']
    assert EARLIER not in messages[-1]['content'] and 'Copper Teacup' not in messages[-1]['content']


def test_no_history_card_retains_two_messages_and_hardware_boundaries():
    messages, _, _ = compile(inputs())
    assert [m['role'] for m in messages] == ['system', 'user']
    assert 'You have no tools and cannot change the session' in messages[0]['content']
    assert 'Never say you changed, or will change' in messages[0]['content']


def test_role_overhead_is_included_in_existing_hard_budget():
    messages, _, diagnostics = compile(inputs() | {'narrative_context': deepcopy(NARRATIVE)},
                                      [{'role': 'user', 'content': EARLIER}], target_prompt_tokens=512)
    assert len(messages) == 3
    assert diagnostics['estimated_prompt_tokens'] <= diagnostics['budget']['hard_prompt_tokens']


# Message digests captured from checkpoint 07f9d5d on these deterministic inputs; re-captured for the
# system rules rewrite (feature/system-prompt-v2), where restoring the old system text gives the old digests.
# These cover the complete messages, not only the roles or the final user text.
@pytest.mark.parametrize('policy,narrative,expected', [
    ('last_user', False, 'd67c29505dda8dfae5a1f6658eccecc0258e834f64d89c2140543bc544f8ed6e'),
    ('last_user', True, '31ccc6fb58db619455d72808b79780117f60fbf35a3ebac6431586b20259bc5c'),
    ('ranked', True, '81c79f4cbb8a0615cae0e6422454b049eac5c00b39d17fe302459a3760053119'),
])
def test_non_card_messages_are_byte_unchanged(policy, narrative, expected):
    summary = inputs(False)
    if narrative:
        summary['narrative_context'] = deepcopy(NARRATIVE)
    history = [{'role': 'user', 'content': STANDING}, {'role': 'user', 'content': EARLIER},
               {'role': 'assistant', 'content': 'Marigold.'}]
    messages, _, _ = compile(summary, history, policy)
    assert hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest() == expected
