# SPDX-License-Identifier: AGPL-3.0-only
"""v0.7.0-rc2 full-review regressions: Cancel stops a user settings decision, and a memory
storage failure never strands a reply. No model or device is contacted."""
import asyncio
from companion_ai.conversation import ConversationService, SETTINGS_CANCELLED
from companion_ai.models import AIConfig, MemoryConfig
from companion_ai.storage import SettingsStore
from tests.ai.support import ObservationFixture
from tests.ai.test_settings_control import report

PROPOSAL = '{"change":"intensity","value":75,"reason":"A little stronger."}'


def settings_adapter(started, release):
    class Adapter:
        config = AIConfig(model='review-test')
        mode = 'ollama'
        async def decide_settings(self, *args):
            started.set()
            await release.wait()
            return PROPOSAL
    return Adapter()


async def test_cancel_during_a_user_settings_decision_sends_no_proposal_and_no_reply():
    started, release, frames = asyncio.Event(), asyncio.Event(), []
    state = ObservationFixture(); state.report = report()
    speech = ConversationService(state, frames.append, settings_adapter(started, release))
    caller = asyncio.create_task(speech.decide_for_user('Make it stronger'))
    await started.wait()
    speech.interrupt()
    release.set()
    result = await caller
    assert result is SETTINGS_CANCELLED and not caller.cancelled()
    assert not any(m['type'] == 'settings_request' for m in frames)
    await speech.close()


async def test_cancel_while_waiting_for_the_outcome_returns_cancelled_and_leaves_the_change_to_the_card_path():
    started, release, frames = asyncio.Event(), asyncio.Event(), []
    release.set()
    state = ObservationFixture(); state.report = report()
    speech = ConversationService(state, frames.append, settings_adapter(started, release))
    caller = asyncio.create_task(speech.decide_for_user('Make it stronger'))
    for _ in range(50):
        await asyncio.sleep(0)
        if any(m['type'] == 'settings_request' for m in frames):break
    request = next(m for m in frames if m['type'] == 'settings_request')
    speech.interrupt()
    assert await caller is SETTINGS_CANCELLED
    assert speech.settings.ledger[request['id']]['awaited'] is False
    await speech.close()


async def test_a_cancelled_caller_cancels_the_decision_too():
    started, release, frames = asyncio.Event(), asyncio.Event(), []
    state = ObservationFixture(); state.report = report()
    speech = ConversationService(state, frames.append, settings_adapter(started, release))
    caller = asyncio.create_task(speech.decide_for_user('Make it stronger'))
    await started.wait()
    decision = speech.settings.task
    caller.cancel()
    await asyncio.gather(caller, return_exceptions=True)
    await asyncio.sleep(0)
    assert caller.cancelled() and decision.cancelled()
    await speech.close()


def failing_store(directory, prefix):
    class FailingStore(SettingsStore):
        def write(self, name, value):
            if name.startswith(prefix):raise OSError('simulated ENOSPC')
            return super().write(name, value)
    return FailingStore(directory)


async def reply_with_failing(tmp_path, prefix):
    class Adapter:
        config = AIConfig(model='review-test')
        memory = MemoryConfig(persist_between_sessions=True)
        store = failing_store(tmp_path, prefix)
        async def reply(self, *args, **kwargs):return 'Hello there.'
    frames = []
    speech = ConversationService(ObservationFixture(), frames.append, Adapter())
    speech.request('Hello', user=True)
    await speech.task
    await speech.close()
    return speech, frames


async def test_history_storage_failure_still_delivers_the_reply_and_reports_it(tmp_path):
    speech, frames = await reply_with_failing(tmp_path, 'memory/models/')
    assert any(m['type'] == 'speech' and m['text'] == 'Hello there.' for m in frames)
    notes = [m['storage_error'] for m in frames if m['type'] == 'ai_diagnostics' and m.get('storage_error')]
    assert notes and 'conversation history' in notes[0]
    assert [m['content'] for m in speech.history] == ['Hello', 'Hello there.']


async def test_story_memory_storage_failure_still_delivers_the_reply(tmp_path):
    speech, frames = await reply_with_failing(tmp_path, '')
    assert any(m['type'] == 'speech' for m in frames)
    assert not any(m['type'] == 'conversation_error' for m in frames)
