# SPDX-License-Identifier: AGPL-3.0-only
import pytest
from tests.fork.context_evaluation import run,MODELS,SCENARIO

@pytest.mark.parametrize('model',MODELS)
async def test_fifty_step_simulated_context_lifecycle_for_both_characters(model):
 result=await run(model,'f28')
 assert len(result['turns'])==len(SCENARIO)==50 and result['thinking_off_verified'] and not result['metadata_leakage']
 assert sum(bool(t['reply']) for t in result['turns'])>=30
 assert not any(t['error'] for t in result['turns'])
 assert any(t['context'].get('focus',{}).get('category')=='react_event' for t in result['turns'])
 for turn in result['turns']:
  if turn['calls'] and turn['context'].get('budget'):
   assert turn['context']['estimated_prompt_tokens']<=turn['context']['budget']['hard_prompt_tokens']
