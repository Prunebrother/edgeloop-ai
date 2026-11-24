#!/usr/bin/env python3
"""AGPL-3.0-only. Conservative source-integrity/privacy checks; no uploads or services.
Pattern scanning cannot prove absence of every secret or identity. Review is required.
"""
from pathlib import Path
import argparse
from hashlib import sha256
import json
import re
import subprocess
import sys

try:
    from story_art import load_registry, validate as validate_story
except ModuleNotFoundError:
    from tools.story_art import load_registry, validate as validate_story

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
IGNORED={'.git','.venv','node_modules','__pycache__','.pytest_cache'}

# A public test build (pre-release or a tester-facing rc) may ship story text that is still Draft or Placeholder and
# story art slots that are not integrated yet: the game already badges them. Everything else stays blocking,
# including explicit story art. A stable release never passes --test-build.
TEST_BUILD_ALLOWED={'draft campaign narrative','placeholder campaign narrative','story slot is not integrated'}

def validate(approved_identities=(),test_build=False):
    manifest=json.loads((ROOT/'MANIFEST.json').read_text())
    errors=[]
    included=manifest['included']
    found=set()
    patterns={
        'absolute home path':rb'/(?:home|Users)/[A-Za-z0-9_.-]+/',
        'private key':rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
        'credential token':rb'(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})',
        'device MAC':rb'(?i)\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b',
    }
    for p in ROOT.rglob('*'):
        parts=p.relative_to(ROOT).parts
        if parts[0] in {'runtime','models','wheelhouse','dist'} or any(x in IGNORED or x.endswith('.egg-info') for x in parts):continue
        n=str(p.relative_to(ROOT))
        if p.is_symlink():errors.append((n,'symlink not allowed'));continue
        if not p.is_file() or n in {'MANIFEST.json','BUNDLE.json'}:continue
        found.add(n);b=p.read_bytes()
        expected=included.get(n)
        if expected is None or sha256(b).hexdigest()!=expected['sha256']:errors.append((n,'missing or changed manifest entry'))
        if p.suffix in {'.db','.sqlite','.sqlite3','.jsonl','.gguf','.safetensors','.pyc','.log','.dump'} or '.ai-data' in parts:errors.append((n,'private/generated file category'))
        if n.startswith('.env') and n!='.env.example':errors.append((n,'environment file'))
        for category,pattern in patterns.items():
            if re.search(pattern,b):errors.append((n,category))
    for n in set(included)-found:errors.append((n,'missing packaged file'))
    if (ROOT/'.git').is_dir():
        def git(*a):return subprocess.run(['git','--no-optional-locks','-C',str(ROOT),*a],capture_output=True,text=True,check=True).stdout
        if git('remote','get-url','origin').strip()!='https://github.com/Prunebrother/edgeloop-ai.git':errors.append(('.git','unexpected publication remote'))
        refs=git('for-each-ref','--format=%(objectname)').splitlines()
        if refs:
            metadata=git('log','--all','--format=%an <%ae>%n%cn <%ce>%n%B')
            for category,pattern in patterns.items():
                if re.search(pattern,metadata.encode()):errors.append(('.git',category))
            identities=git('log','--all','--format=%an <%ae>%n%cn <%ce>').splitlines()
            # Approval belongs to the review invocation, not a published account-ID allowlist.
            if not set(identities).issubset(set(approved_identities)):errors.append(('.git','unreviewed commit identity'))
    catalog=json.loads((ROOT/'src/assets/characters/manifest.json').read_text())
    story_only={cid for cid,c in catalog['characters'].items() if c.get('role')=='story'}
    for character_id, character in catalog['characters'].items():
        if character.get('status')=='placeholder':errors.append((character_id,'placeholder manifest character'))
        if character.get('role') not in (None,'story'):errors.append((character_id,'unknown character role'))
    # Story-only characters (HELIX-030): a neutral portrait at least, no model, no animation clips.
    for character_id in sorted(story_only):
        character=catalog['characters'][character_id]
        if not character['expressions'].get('neutral'):errors.append((character_id,'story character without a neutral portrait'))
        if character.get('animations'):errors.append((character_id,'story character with animations'))
        if character_id in catalog['models'].values():errors.append((character_id,'story character mapped to a model'))
    story_root=ROOT/'src/assets/story'
    for registry_path in sorted(story_root.glob('*/ASSETS.json')):
        label=registry_path.relative_to(ROOT).as_posix()
        try:
            if registry_path.is_symlink():raise ValueError('symlink registry is not allowed')
            registry=load_registry(registry_path)
            if registry['campaign']!=registry_path.parent.name:raise ValueError('registry: campaign does not match directory')
            validate_story(registry,registry_path.parent)
        except (OSError,ValueError) as exc:
            errors.append((label,str(exc)));continue
        for slot,item in registry['slots'].items():
            if item['status']!='integrated':errors.append((f"{registry['campaign']}/{slot}",'story slot is not integrated'))
            if item['explicit']:errors.append((f"{registry['campaign']}/{slot}",'explicit story slot'))
    from companion_ai.campaign import Book, Narrative
    from companion_ai.narrative_lint import lint
    book=Book.load(ROOT/'config/campaigns',story_dir=story_root,manifest=ROOT/'src/assets/characters/manifest.json')
    # Orphan narratives used to receive the placeholder check too; keep checking them rather than silently dropping them.
    for narrative_path in sorted((ROOT/'config/campaigns').glob('*/narrative.json')):
        cid=narrative_path.parent.name
        if cid not in book.narratives:
            try:book.narratives[cid]=Narrative.model_validate_json(narrative_path.read_text())
            except ValueError:errors.append((f'{cid}:narrative.json','invalid campaign narrative'))
    registries={}
    for registry_path in sorted(story_root.glob('*/ASSETS.json')):
        try:registries[registry_path.parent.name]=json.loads(registry_path.read_text())
        except (OSError,ValueError):pass  # The registry validator above already reports the error.
    narrative_findings=lint(book,catalog,registries,release=True)
    for finding in narrative_findings:
        if finding.severity!='error':continue
        # Keep the established category/path pair; detailed locations remain in narrative_findings.
        path=finding.campaign if finding.message=='placeholder campaign narrative' else f'{finding.campaign}:{finding.location}'
        if (path,finding.message) not in errors:errors.append((path,finding.message))
    portraits={p.lstrip('/') for c in catalog['characters'].values() for p in c['expressions'].values()}
    animations = set()
    for character in catalog['characters'].values():
        for expression, clips in character.get('animations', {}).items():
            if expression not in catalog['expressions'] or not isinstance(clips, dict):
                raise ValueError('Invalid animation expression or formats')
            for fmt, asset in clips.items():
                if fmt not in {'webm', 'mp4'} or not isinstance(asset, str) or not re.fullmatch(
                        r'/Character_Art/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.' + fmt, asset):
                    raise ValueError('Invalid curated animation path or format')
                animations.add(asset.lstrip('/'))

    # Every manifest character ships the full expression set (12 each), however many characters there are.
    # Story-only characters ship only the portraits they declare.
    expected=12*(len(catalog['characters'])-len(story_only))+sum(len(catalog['characters'][c]['expressions']) for c in story_only)
    if len(portraits)!=expected or any(not (ROOT/p).is_file() for p in portraits):errors.append(('Character_Art','incomplete expression portraits'))
    if any(not (ROOT/p).is_file() for p in animations):errors.append(('Character_Art','missing declared animation'))
    if {n for n in found if n.startswith('Character_Art/')}!=portraits | animations:errors.append(('Character_Art','unexpected unreferenced art'))
    allowed=[(n,c) for n,c in errors if test_build and c in TEST_BUILD_ALLOWED]
    errors=[e for e in errors if e not in allowed]
    return {'passed':not errors,'packaged_files':len(included),'errors':[{'path':n,'category':c} for n,c in errors],
            'test_build':test_build,'test_build_allowed':[{'path':n,'category':c} for n,c in allowed],
            'narrative_findings':[finding._asdict() for finding in narrative_findings],
            'limits':'Pattern and hash checks only. Does not certify licensing, arbitrary secrets, human identities, or physical safety.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-identity',action='append',default=[])
    parser.add_argument('--test-build',action='store_true',help='allow Draft/Placeholder story text and unintegrated story art (public test builds only)')
    args=parser.parse_args()
    try:result=validate(args.approved_identity,test_build=args.test_build)
    except (OSError,ValueError,subprocess.CalledProcessError) as exc:
        print(json.dumps({'passed':False,'error_type':type(exc).__name__}));sys.exit(1)
    print(json.dumps(result,indent=2));sys.exit(0 if result['passed'] else 1)
