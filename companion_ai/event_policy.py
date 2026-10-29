# SPDX-License-Identifier: AGPL-3.0-only
"""Classification of proven F2.3 events only. Does not detect or control anything."""
SELECTION_EVENTS = frozenset({'experience_changed','goal_changed'})
REACTIVE_EVENTS = SELECTION_EVENTS | {'came_early','completion_accepted'}
LIFECYCLE_EVENTS = frozenset({'session_started','session_resumed','came_early','completion_accepted'})
REACTION_EVENTS = REACTIVE_EVENTS | LIFECYCLE_EVENTS
MAJOR = frozenset({'session_started', 'session_resumed', 'edge', 'milestone', 'stop', 'experience_changed', 'goal_changed', 'came_early','completion_accepted'})
CRITICAL = frozenset({'signal_lost', 'no_contact'})

def significance(kind, previous, current):
    if kind in CRITICAL:return 'critical', 100
    if kind == 'device_changed' and previous and current['status'] != 'IDLE':
        before, after = previous['devices'], current['devices']
        if any(before.get(k) is True and after.get(k) is False for k in ('ble','handy','intiface','tcode','vacuglide')):
            return 'critical', 100
    if kind in {'came_early','completion_accepted'}:return 'major',70
    if kind in MAJOR:return 'major', 50
    return 'routine', 10
