# SPDX-License-Identifier: AGPL-3.0-only
import json,pytest
from companion_ai.event_intelligence import EventConfig,DetectorRule,EventIntelligence,DerivedEvent,preset,load_config
from companion_ai.storage import SettingsStore
from tests.fork.event_replay import Replay,SCENARIOS,EXAMPLE

@pytest.mark.parametrize('scenario,kind',[('rapid_rise','rapid_rise'),('rapid_fall','rapid_fall'),('sustained_elevation','sustained_elevation'),('fluctuations','fluctuations')])
def test_evidence_backed_detectors(scenario,kind):
 r=Replay();events=r.run(SCENARIOS[scenario]);selected=[e for e in events if e['kind']==kind]
 assert selected
 for e in selected:
  assert DerivedEvent.model_validate(e).sample_count>=5
  assert e['last_at_ms']>e['first_at_ms'] and e['simulated'] and e['source']=='simulator'
  assert e['category']=='derived' and e['significance']!='critical'
  assert e['quality']=='sufficient_validated_samples' and e['session_id']==r.observation.session_id
 assert len(selected)<=1 # latch/cooldown prevents repeated narration

def test_stable_optional_noise_spike_and_insufficient_samples():
 c=EventConfig();assert not c.detectors['stable'].enabled
 c.detectors['stable'].enabled=True
 assert any(e['kind']=='stable' for e in Replay(c).run(SCENARIOS['stable']))
 r=Replay();r.state['details']['resting_bpm']=85
 assert not r.run(SCENARIOS['single_spike'])
 assert not Replay().run([(0,85),(1,120)])
 assert not [e for e in Replay().run(SCENARIOS['gradual_rise']) if e['kind']=='rapid_rise']

def test_recovery_requires_earlier_measured_baseline_and_prior_elevation():
 c=EventConfig();c.detectors['recovery'].window_seconds=30.
 events=Replay(c).run(SCENARIOS['recovery'])
 e=next(e for e in events if e['kind']=='recovery')
 assert e['reference_kind']=='earlier_measured_reference' and e['reference_bpm']==85
 assert e['change_bpm']<0
 assert not any(e['kind']=='recovery' for e in Replay(c).run(SCENARIOS['rapid_fall']))

def test_sparse_example_conservative_defaults_and_configured_evidence():
 assert not any(e['kind'] in {'rapid_rise','rapid_fall'} for e in Replay().run(EXAMPLE))
 c=EventConfig()
 for k in ['rapid_rise','rapid_fall','recovery']:c.detectors[k].window_seconds=40.
 c.detectors['recovery'].hysteresis_bpm=8.;c.detectors['rapid_fall'].hysteresis_bpm=8.
 events=Replay(c).run(EXAMPLE)
 assert {'rapid_rise','rapid_fall','recovery'}<={e['kind'] for e in events}
 assert all(e['sample_count']>=5 for e in events)
 assert len({e['id'] for e in events})==len(events)

def test_reference_setting_is_never_a_measured_baseline():
 r=Replay();e=next(e for e in r.run(SCENARIOS['sustained_elevation']) if e['kind']=='sustained_elevation')
 assert e['reference_kind']=='configured_resting_setting_not_measured_baseline'
 c=EventConfig();c.detectors['sustained_elevation'].reference='narrative_threshold';c.detectors['sustained_elevation'].reference_bpm=90.
 assert not any(e['kind']=='sustained_elevation' for e in Replay(c).run(SCENARIOS['sustained_elevation']))

@pytest.mark.parametrize('action',[{'source':'unavailable'},{'status':'PAUSED'},{'reset':True},{'source':'BLE sensor'},{'reconnect':True}])
def test_segmentation_never_bridges_invalid_period_or_source(action):
 r=Replay()
 for bpm in [84,85,86,87]:r.step(bpm)
 before=r.observation.measurement_segment;r.step(110,**action)
 assert r.observation.measurement_segment>before
 assert not any(e['kind']=='rapid_rise' for e in r.step(120))

def test_duplicate_timestamps_missing_bpm_and_bounded_memory():
 r=Replay();r.step(85);stamp=r.state['details']['hr_recorded_at_ms']
 for _ in range(20):r.step(stamp=stamp)
 assert len(r.observation.samples)==1 and not r.events
 for _ in range(800):r.step(85)
 assert len(r.observation.samples)<=181 and len(r.detector.history)<=48
 r.step(source='unavailable');assert not r.observation.samples and r.observation.hr is None

def test_config_change_applies_only_to_future_samples_and_presets_are_isolated():
 r=Replay();r.run(SCENARIOS['rapid_rise']);r.detector.configure(EventConfig())
 assert r.detector.evaluate(r.observation)==[]
 quiet=preset('quiet');balanced=preset('balanced');assert quiet.proactive_interval_seconds>balanced.proactive_interval_seconds
 quiet.detectors['rapid_rise'].threshold_bpm=50.;assert balanced.detectors['rapid_rise'].threshold_bpm==15.

@pytest.mark.parametrize('values',[{'threshold_bpm':0},{'window_seconds':1801},{'min_samples':1},{'hysteresis_bpm':16},{'duration_seconds':31.,'window_seconds':20.},{'significance':'critical'}])
def test_invalid_detector_settings(values):
 with pytest.raises(ValueError):DetectorRule.model_validate(values)

def test_versioned_config_defaults_migration_unknown_and_preferences(tmp_path):
 store=SettingsStore(tmp_path);store.write('event-intelligence.json',{'schema_version':0,'enabled':False})
 c,error=load_config(store);assert not error and not c.enabled and len(c.detectors)==9
 store.write('event-intelligence.json',{'schema_version':999});c,error=load_config(store);assert error and not c.enabled
 assert store.read('event-intelligence.json')['schema_version']==999
 with pytest.raises(ValueError):EventConfig.model_validate({'detectors':{'fake':{}}})
 with pytest.raises(ValueError):EventConfig.model_validate({'preferences':{'evelyn':{'physiology':-1}}})
 c=EventConfig();c.preferences['evelyn']['physiology']=0
 assert c.relevance('evelyn-narrative-v1:latest','physiology')==0
 assert c.relevance('daisy-narrative-v1:latest','physiology')==1
 assert c.relevance('unknown:latest','physiology')==1


def test_physiology_window_cannot_exceed_shared_history_budget():
 with pytest.raises(ValueError):EventConfig.model_validate({'detectors':{'rapid_rise':{'window_seconds':121.}}})
 c=EventConfig.model_validate({'detectors':{'quiet':{'window_seconds':600.}}});assert c.detectors['quiet'].window_seconds==600

def test_changed_duplicate_and_out_of_order_measurements_break_evidence():
 r=Replay();r.step(85);stamp=r.state['details']['hr_recorded_at_ms']
 r.step(130,stamp=stamp);assert r.observation.hr is None and not r.observation.samples
 r.step(90);assert r.observation.hr==90 and len(r.observation.samples)==1
 r.step(120,stamp=stamp-1);assert r.observation.hr is None and not r.observation.samples
