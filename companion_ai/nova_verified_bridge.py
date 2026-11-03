"""Read-only Nova cross-companion history projection for EdgeLoop F2.9.

Adapter for the existing SessionJournal schema, not a second memory store.
Never accepts session history from LLM/user input. All permissions and raw
journal records must be obtained from the trusted SessionJournal instance.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from statistics import mean
from collections import defaultdict
import math
import re

CHARACTERS = frozenset({'nova', 'evelyn', 'daisy', 'celeste'})
WINDOW_DAYS = 30
MAX_AGE_DAYS = 90
MAX_ROWS = 100


def requested_cross_companions(prompt: str, model_scope: str) -> frozenset[str]:
    """Only a Nova historical request EXPLICITLY naming another character qualifies."""
    from companion_ai.session_journal import companion, SessionJournal
    if companion(model_scope) != 'nova' or not SessionJournal.relevant(prompt):
        return frozenset()
    names = frozenset(x.lower() for x in re.findall(r'\b(?:Evelyn|Daisy|Celeste|Nova)\b', prompt, re.I))
    return names if names - {'nova'} else frozenset()


def _utc(value):
    """Accept only documented-possible ISO and epoch-ms timestamps; never guess units."""
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return dt.astimezone(timezone.utc) if dt.tzinfo else None
        if type(value) in (int, float) and math.isfinite(value) and 1e12 < value < 5e12:
            return datetime.fromtimestamp(value / 1000, timezone.utc)
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _number(value, maximum):
    if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum:
        return float(value)
    return None


def _denied(reason):
    return {'status': 'denied', 'reason': reason, 'records_used': 0, 'by_companion': {}, 'may_claim_journal_read': False}


def summarize_existing_journal(journal, targets: frozenset[str], *, now: datetime | None = None, days: int = WINDOW_DAYS) -> dict:
    """Aggregate trusted retained rows; never expose identifiers, individual records or HR assumptions.

    Rows containing several companions are excluded: attributing their totals to
    one companion would invent provenance. Unrecognized shapes are skipped.
    """
    if targets - CHARACTERS or not targets or type(days) is not int or not 1 <= days <= MAX_AGE_DAYS:
        raise ValueError('Invalid Nova aggregate query')
    if journal is None or getattr(journal, 'error', 'unavailable'):
        return _denied('journal_unavailable')
    data = getattr(journal, 'data', {})
    if data.get('recording') is not True:
        return _denied('journal_recording_off')
    if data.get('ai_access') is not True:
        return _denied('journal_ai_access_off')
    if data.get('nova_cross_companion') is not True:
        return _denied('nova_cross_companion_off')
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or not now.tzinfo or now.utcoffset() is None:
        raise ValueError('UTC-aware clock required')
    now = now.astimezone(timezone.utc)
    start = now - timedelta(days=days)
    rows = data.get('records')
    if not isinstance(rows, list):
        return _denied('journal_unavailable')
    retained = rows[-MAX_ROWS:]
    groups = defaultdict(list)
    excluded_shared = 0
    skipped_unknown = 0
    for row in retained:
        if not isinstance(row, dict):
            skipped_unknown += 1; continue
        stamp = _utc(row.get('first_observed_at')) or _utc(row.get('start_at'))
        if stamp is None or not start <= stamp <= now:
            continue
        companions = row.get('companions', [])
        if not isinstance(companions, list):
            skipped_unknown += 1; continue
        names = {c.get('companion', '').lower() for c in companions if isinstance(c, dict) and type(c.get('companion')) is str}
        if len(names) != 1:
            excluded_shared += 1; continue
        name = next(iter(names))
        if name not in targets:
            continue
        duration = _number(row.get('active_running_seconds'), 172800)
        edges = row.get('edges')
        edges = edges if type(edges) is int and 0 <= edges <= 1000000 else None
        groups[name].append((duration, edges))
    result = {}
    for name in sorted(targets):
        group = groups.get(name, [])
        if not group:
            continue
        durations = [d / 60 for d, _ in group if d is not None]
        edges = [e for _, e in group if e is not None]
        result[name] = {
            'session_count': len(group),
            'duration_known_sessions': len(durations),
            'active_duration_mean_minutes_known': round(mean(durations), 2) if durations else None,
            'active_duration_total_minutes_known': round(sum(durations), 2) if durations else None,
            'edge_count_known_sessions': len(edges),
            'engine_edge_count_mean_known': round(mean(edges), 2) if edges else None,
            'engine_edge_count_total_known': sum(edges) if edges else None,
        }
    # Recheck after processing; permission changes invalidate even assembled results.
    if journal.data is not data or journal.error or data.get('recording') is not True or data.get('ai_access') is not True or data.get('nova_cross_companion') is not True:
        return _denied('permission_changed')
    return {
        'status': 'authorized_data' if result else 'no_retained_records',
        'source': 'authorized_session_journal_aggregate',
        'window_days': days,
        'records_used': sum(v['session_count'] for v in result.values()),
        'by_companion': result,
        'excluded_multi_companion_records': excluded_shared,
        'skipped_unknown_records': skipped_unknown,
        'retained_limit': MAX_ROWS,
        'may_claim_journal_read': bool(result),
        'limitations': 'Only retained, eligible single-companion sessions in the bounded window; incomplete/unknown fields excluded; not lifetime history. No transcripts or biometric means.',
    }
