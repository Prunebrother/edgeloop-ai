# SPDX-License-Identifier: AGPL-3.0-only
"""Read-only history for Arrival and Closing cards: one earlier session, and how it compares.

Nothing here writes. The result is a small projection, never a raw Journal record: no session
identifiers, companion lists, heart-rate ranges, settings or other sessions reach the model.
Missing history, unreadable history, denied access and an incomplete lookup stay distinct states,
because only a complete, permitted lookup may support the words "first session".
"""
import re
from .session_journal import MAX_RECORDS, companion

FOUND, NONE, DENIED, UNAVAILABLE, INCOMPLETE = 'found', 'none', 'denied', 'unavailable', 'incomplete'
# A completion-report checkpoint holds counters from mid-session, so it is not a final result.
COMPARABLE = {'final_counter_captured', 'final_duration_unavailable'}
LABEL = re.compile(r'^[A-Za-z0-9_ -]{1,40}$')


def family(scope):
    """The character behind a model name, so that a new model version can't claim a first meeting."""
    return companion(scope).split(':')[0].split('-')[0].casefold()


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


def label(value):
    return value if isinstance(value, str) and LABEL.match(value) else None


def outcome(record):
    """The person's report, an accepted application event and a plain stop are different facts."""
    status = record.get('completion_status')
    if status == 'user_reported': return 'user_reported'
    if status == 'accepted_application_event': return 'application_event'
    return 'stopped' if record.get('termination') == 'manual_stop' else 'unknown'


def project(record):
    return {'edges': number(record.get('edges')), 'seconds': number(record.get('active_running_seconds')),
            'experience': label(record.get('experience')), 'goal': label(record.get('goal')),
            'outcome': outcome(record), 'comparable': record.get('completeness') in COMPARABLE}


def previous_session(journal, scope, exclude=(), seen=()):
    """The newest earlier session that belonged to this exact model scope alone.

    `exclude` holds stable session identities, so a session the Journal has just persisted is
    never compared with itself. `seen` holds sessions known by other means; one the Journal
    doesn't hold means that "no records" can't be read as "no sessions".
    """
    if journal is None or journal.error: return {'status': UNAVAILABLE}
    data = journal.data
    if not data.get('ai_access'): return {'status': DENIED}
    records = [r for r in data.get('records', ()) if isinstance(r, dict)]
    malformed = len(records) != len(data.get('records', ()))
    ids = {r.get('session_id') for r in records}
    own, related = [], False
    for index, record in enumerate(records):
        if record.get('session_id') in exclude: continue
        companions = record.get('companions')
        scopes = {c.get('model_scope') for c in companions if isinstance(c, dict)} if isinstance(companions, list) else set()
        if scopes == {scope}: own.append((number(record.get('final_verified_at_ms')) or 0, index, record))
        # Shared, unattributed or sibling-model rows stay unread, but they do rule out "first".
        elif not scopes or scope in scopes or any(family(s or '') == family(scope) for s in scopes): related = True
    if own:
        record = max(own, key=lambda row: row[:2])[2]
        return {'status': FOUND, 'prior': project(record), 'finished_at_ms': number(record.get('final_verified_at_ms'))}
    complete = (data.get('recording') is True and not malformed and not related and len(records) < MAX_RECORDS
                and not (set(data.get('closed_sessions', ())) | set(seen)) - ids - set(exclude))
    return {'status': NONE if complete else INCOMPLETE}


def compare(current, prior):
    """Directions and differences only. Nothing here says that a direction is good or bad."""
    if not prior or not prior.get('comparable'): return None
    result = {}
    for field in ('edges', 'seconds'):
        new, old = current.get(field), prior.get(field)
        if new is None or old is None: continue
        result[field] = {'direction': 'increase' if new > old else 'decrease' if new < old else 'unchanged', 'difference': abs(new - old)}
    for field in ('experience', 'goal'):
        new, old = current.get(field), prior.get(field)
        if new is not None and old is not None: result[field + '_changed'] = new != old
    # How each session ended is kept beside the figures: a report and a stop aren't the same fact.
    if current.get('outcome') and prior.get('outcome'): result['outcome'] = {'current': current['outcome'], 'prior': prior['outcome']}
    return result


def spoken_time(seconds):
    minutes, rest = divmod(int(seconds), 60)
    said = lambda value, unit: f"{value} {unit}{'' if value == 1 else 's'}"
    if not minutes: return said(rest, 'second')
    return said(minutes, 'minute') + (' ' + said(rest, 'second') if rest else '')


def edges_and_time(record):
    edges, seconds = record.get('edges'), record.get('seconds')
    parts = []
    if edges is not None: parts.append(f"{edges} edge{'' if edges == 1 else 's'}")
    if seconds is not None: parts.append(spoken_time(seconds))
    return ' in '.join(parts)


def plain_record(history):
    """The recorded figures of a Closing and nothing more, for when a draft could not be used. Holds no direction to get wrong."""
    now = edges_and_time(history.get('current') or {})
    if not now: return None
    # Only figures both sessions have: "3 edges against 9 minutes" compares nothing.
    comparison = history.get('comparison') or {}
    before = edges_and_time({k: v for k, v in (history.get('prior') or {}).items() if k in comparison and k in ('edges', 'seconds')})
    return f"{now} this time, against {before} last time." if before else f"{now} this time."


def comparison_words(history):
    """The worked-out comparison as one sentence with this session as its subject, or None."""
    comparison = history.get('comparison') or {}
    parts = []
    joiner = 'than'
    if edges := comparison.get('edges'):
        same = edges['direction'] == 'unchanged'
        parts.append('had the same number of edges' if same else f"had {edges['difference']} {'more' if edges['direction'] == 'increase' else 'fewer'} edge{'' if edges['difference'] == 1 else 's'}")
        joiner = 'as' if same else 'than'
    if seconds := comparison.get('seconds'):
        same = seconds['direction'] == 'unchanged'
        parts.append('ran the same length' if same else f"ran {spoken_time(seconds['difference'])} {'longer' if seconds['direction'] == 'increase' else 'shorter'}")
        joiner = 'as' if same else 'than'
    # The last part takes the ending: "the same number of edges and ran 5 minutes shorter than".
    return f"This session {' and '.join(parts)} {joiner} the last one." if parts else None


def since_words(seconds):
    """Approximate on purpose. No calendar date or clock time is ever supplied."""
    if seconds is None or seconds < 0: return None
    hours, days = seconds / 3600, seconds / 86400
    if hours < 1: return 'less than an hour ago'
    if hours < 1.5: return 'about an hour ago'
    if hours < 24: return f'about {round(hours)} hours ago'
    if days < 1.5: return 'about a day ago'
    if days < 14: return f'about {round(days)} days ago'
    if days < 60: return f'about {round(days / 7)} weeks ago'
    if days < 548: return f'about {round(days / 30)} months ago'
    return f'about {round(days / 365)} years ago'
