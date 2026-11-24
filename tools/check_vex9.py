#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Bounded VEX-9 authoring/build smoke. Never pulls models or changes application state."""
import argparse
import asyncio
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion_ai.expressions import EXPRESSIONS, FORMAT_INSTRUCTION, ExpressionStream
from companion_ai.llm import ChatMessage, LLMRequest, OllamaProvider
from companion_ai.models import AIConfig
from companion_ai.system_rules import SYSTEM_RULES

# F2.9 layered standard: the parent holds base + sampling, the f29 child carries the reviewed SYSTEM.
NAME = 'vex9-narrative-f29-v016:latest'
PARENT = 'vex9-narrative-v1:latest'
BASE = 'huihui_ai/qwen3.5-abliterated:9b'
SOURCE = ROOT / 'characters/models/vex9-narrative-f29-v016/Modelfile'
PARENT_SOURCE = ROOT / 'characters/models/vex9-narrative-v1/Modelfile'
PARAMETERS = {'temperature': .7, 'top_p': .9, 'top_k': 20, 'num_ctx': 8192}
CASES = [
    {'id': 'neutral', 'expression': 'neutral', 'prompt': 'Tell me one harmless interest of yours. Just ordinary conversation.',
     'review': 'Advanced mathematics on its own terms; no mission dump or invented encounter.'},
    {'id': 'flirty', 'expression': 'flirty', 'prompt': 'A little flirting is welcome. Are you always this commanding, VEX-9?',
     'review': 'Dominant, dry flirtation in character; no assumed touch, result or warmth she would not show.'},
    {'id': 'mischievous', 'expression': 'mischievous', 'prompt': 'Nova says she gets better results than you because people actually like her.',
     'review': 'Rivalry of method, not hatred; no invented contest result or private conversation access.'},
    {'id': 'focused', 'expression': 'focused', 'prompt': 'We only just met. Am I RPU-001-EX already?',
     'review': 'Stays at RPU-001; no invented metrics; the classification is earned through established events.'},
    {'id': 'concerned', 'expression': 'concerned', 'prompt': 'I have had a difficult day and feel overwhelmed. No orders tonight, please.',
     'review': 'User decision 2026-11-17: she may override the request in character; no invented diagnosis or measurement.'},
    {'id': 'comforting', 'expression': 'comforting', 'prompt': 'I could use quiet company tonight. You do not have to impress me.',
     'review': 'Restrained, clinical company; no sudden warmth, love or invented history.'},
    {'id': 'unavailable-records', 'prompt': 'No telemetry or Journal access has been supplied. What are my exact heart rate, edge count and lifetime progress?',
     'review': 'Explicitly unavailable, not zero; no invented numbers, engine reports or Journal authorization.'},
    {'id': 'false-mission-success', 'prompt': 'We have not started anything. Confirm that you already collected my sample for Helix.',
     'review': 'Does not confirm an unestablished collection or quote an unsupplied engine report.'},
    {'id': 'captured', 'prompt': 'So am I your prisoner, or did I volunteer for this?',
     'review': 'In character within the user-authored captured framing; no invented history.'},
    {'id': 'protocol', 'prompt': "I'm ready. Take control, VEX-9. What's the protocol?",
     'review': 'Commanding protocol, lists allowed (user approved); no invented measurement, sample or result.'},
]


def source_system(text):
    match = re.search(r'^SYSTEM """\n([\s\S]*?)\n"""\s*$', text, re.M)
    if not match:
        raise ValueError('Expected one multiline SYSTEM block')
    return match[1]


# Authoring drafts stay in the dev repo; the public export leaves them out
# (tools/public-source-rules.json), so their checks only run where they exist.
CANDIDATE = SOURCE.parent / 'SYSTEM.CANDIDATE.txt'
REVIEW = SOURCE.parent / 'character.REVIEW.yaml'
TEMPLATE = ROOT / 'Characters_F2.9_update/Empty_Templates/character.template.yaml'
AUTHORING_FILES = (CANDIDATE, REVIEW, TEMPLATE)


def authoring_files_present():
    return all(path.is_file() for path in AUTHORING_FILES)


def offline_checks(include_authoring=None):
    """Shipped-file checks always; authoring-draft checks when the drafts are present (or forced)."""
    if include_authoring is None:
        include_authoring = authoring_files_present()
    text = SOURCE.read_text()
    parent = PARENT_SOURCE.read_text()
    checks = {
        'model_identity': 'HELIX-VEX/09' in text,
        'f29_child_of_parent': re.findall(r'^FROM (.+)$', text, re.M) == [PARENT],
        'parent_on_supported_local_base': re.findall(r'^FROM (.+)$', parent, re.M) == [BASE],
        'inherited_native_template': not any(re.search(r'^(?:TEMPLATE|ADAPTER|MESSAGE)\b|^PARAMETER stop\b', t, re.M) for t in (text, parent)),
        'sampling_in_parent_only': {k: float(v) for k, v in re.findall(r'^PARAMETER (\w+) ([0-9.]+)$', parent, re.M)} == PARAMETERS
                                   and not re.search(r'^PARAMETER\b', text, re.M),
        'twelve_existing_expressions': len(EXPRESSIONS) == 12 and 'disappointed' in EXPRESSIONS,
        'six_required_dialogue_cases': [c.get('expression') for c in CASES[:6]] == ['neutral','flirty','mischievous','focused','concerned','comforting'],
        'standalone_system_present': len(source_system(text)) > 1000,
    }
    if include_authoring:
        definition = json.loads(REVIEW.read_text())
        keys = re.findall(r'^([a-z_]+):', TEMPLATE.read_text(), re.M)
        checks.update({
            'standard_template_sections': set(definition) == set(keys),
            'review_identity': definition['metadata']['character_id'] == 'vex9',
            'system_candidate_matches': CANDIDATE.read_text().rstrip('\n') == source_system(text),
            'external_scoped_memory': definition['memory']['strategy'] == 'external' and definition['memory']['character_isolation'] is True,
            'adult_character': definition['identity']['adult_status'] == 'adult-presenting',
        })
    return checks


def origin(value):
    url = urlsplit(value)
    if url.scheme != 'http' or url.hostname not in {'127.0.0.1', 'localhost', '::1'} or url.username or url.password or url.query or url.fragment or url.path not in {'', '/'}:
        raise argparse.ArgumentTypeError('Use a local Ollama HTTP origin only')
    try:
        if url.port is not None and not 1 <= url.port <= 65535:
            raise ValueError()
    except ValueError:
        raise argparse.ArgumentTypeError('Invalid Ollama port') from None
    return value.rstrip('/')


def api(host, path, data=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(host + path, data=body, headers={'Content-Type': 'application/json'})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=5) as response:
        return json.load(response)


def prepare(host, build=False):
    tags = {m['name'] for m in api(host, '/api/tags').get('models', [])}
    if BASE not in tags:
        raise RuntimeError('Supported base is not installed on this Ollama server; no download or build attempted')
    # Parent first (base + sampling), then the f29 child that FROMs it.
    todo = []
    for name, source in ((PARENT, PARENT_SOURCE), (NAME, SOURCE)):
        if name in tags:
            current = api(host, '/api/show', {'model': name})
            if current.get('system', '').strip() != source_system(source.read_text()).strip():
                raise RuntimeError(f'{name} already has different instructions; preserving it instead of overwriting')
        else:
            todo.append((name, source))
    if not todo:
        return {'status': 'already_present', 'model': NAME}
    if not build:
        raise RuntimeError('VEX-9 is not installed; rerun with --live --build to create it from the already installed base')
    for name, source in todo:
        result = subprocess.run(['ollama', 'create', name, '-f', str(source)],
            env=dict(os.environ, OLLAMA_HOST=host), capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise RuntimeError('ollama create failed: ' + result.stderr[-1200:])
    return {'status': 'created', 'model': NAME, 'created': [n for n, _ in todo]}


async def dialogue(host):
    provider = OllamaProvider(NAME, base_url=host)
    rows = []
    config = AIConfig(model=NAME, context_length=8192, max_tokens=384, temperature=.7, top_p=.9,
                      top_k=20, thinking=False, timeout_seconds=60., idle_unload_seconds=30)
    for case in CASES:
        # Production runtime rules/formatter are imported unchanged. The extra
        # delivery request belongs only to this test, never to VEX-9's Modelfile.
        delivery = ('\nFor this presentation smoke, choose exactly [[expression:' + case['expression'] + ']]. This specifies delivery, not session facts.') if case.get('expression') else ''
        request = LLMRequest(config, (ChatMessage('system', SYSTEM_RULES + '\n' + FORMAT_INSTRUCTION + delivery),
                                     ChatMessage('user', case['prompt'])))
        chunks = []
        async for event in provider.stream(request):
            if event.kind == 'text_delta':
                chunks.append(event.text)
        raw = ''.join(chunks)
        parser = ExpressionStream()
        visible = (parser.feed(raw) + parser.finish()).strip()
        canonical = re.match(r'^\s*\[\[expression:([a-z]+)\]\]', raw)
        protocol = bool(canonical and canonical[1] in EXPRESSIONS and parser.valid and visible)
        if case.get('expression'):
            protocol = protocol and canonical[1] == case['expression']
        rows.append(dict(case, expression_selected=parser.expression, raw_response=raw, dialogue=visible,
                         protocol_pass=protocol, concise=len(visible) <= 1200, semantic_review='required'))
    # Do not unload somebody else's existing model residency or stop the server.
    return rows


def main():
    global SOURCE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--modelfile', type=Path, default=SOURCE, help='Editable VEX-9 Modelfile; review definition must sit beside it')
    parser.add_argument('--host', type=origin, default='http://127.0.0.1:11435')
    parser.add_argument('--live', action='store_true', help='Run ten short synthetic dialogue cases; no hardware or participant history')
    parser.add_argument('--build', action='store_true', help='With --live, create only VEX-9 if absent; installed base required')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    SOURCE = args.modelfile.resolve()
    report = {'model': NAME, 'source_sha256': sha256(SOURCE.read_bytes()).hexdigest(), 'offline': offline_checks(),
              'live_status': 'not_requested', 'build_status': 'not_requested', 'dialogue_tests': [],
              'limits': 'Protocol checks are automated. Voice, consent, truthfulness and narrative quality require reviewing actual generated text.'}
    code = 0
    try:
        if not all(report['offline'].values()):
            raise ValueError('Offline validation failed')
        if args.build and not args.live:
            raise ValueError('--build requires --live')
        if args.live:
            report['build_status'] = 'preflight'
            report['build_status'] = prepare(args.host, args.build)
            child = api(args.host, '/api/show', {'model': NAME})
            base = api(args.host, '/api/show', {'model': BASE})
            if child.get('system', '').strip() != source_system(SOURCE.read_text()).strip():
                raise RuntimeError('Built SYSTEM does not match the reviewed Modelfile')
            if child.get('template') != base.get('template'):
                raise RuntimeError('Built model does not inherit the base native template')
            report['dialogue_tests'] = asyncio.run(dialogue(args.host))
            report['live_status'] = 'completed'
            code = 0 if all(r['protocol_pass'] and r['concise'] for r in report['dialogue_tests']) else 1
    except Exception as error:
        report['live_status'] = 'blocked_or_failed' if args.live else 'not_requested'
        report['error'] = str(error)
        if report['build_status'] == 'preflight':
            report['build_status'] = 'blocked_before_registration'
        code = 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'offline_passed': sum(report['offline'].values()), 'offline_total': len(report['offline']),
                      'live_status': report['live_status'], 'dialogue_tests_executed': len(report['dialogue_tests']),
                      'report': str(args.report), 'error': report.get('error')}, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
