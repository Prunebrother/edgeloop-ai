# SPDX-License-Identifier: AGPL-3.0-only
"""Character Builder: player-authored worlds, characters and card decks.

Sources (what the player edits) live in the project-local data directory:

  character-builder/worlds/<world_id>.json          reusable across characters
  character-builder/characters/<character_id>.json  references one world, holds its deck
  character-builder/art/                            the player's portrait inbox
  character-builder/art-store/<sha256>.<ext>        content-addressed copies
  character-builder/packages/<id>/<sha12>.json      composed, versioned packages
  character-builder/active.json                     the activated package, if any

The Character Composer turns (world, character, portrait bytes) into a package. It is a
pure function: no clock, randomness or environment, and canonical JSON, so the same
inputs always give a byte-identical package and the same content hash.

Where authored text goes:
  - world + character -> persona_system, which REPLACES the model's embedded Modelfile
    SYSTEM (OllamaProvider.persona_system). Runtime rules are still appended after it.
  - card brief/occasion -> the existing card turn (context_compiler.card_instruction).
Authored text never reaches any other prompt section, and cards are dialogue only:
they carry no action, setting or device field.
"""
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Literal
from pydantic import Field, ValidationError, field_validator, model_validator
from .event_deck import Card, DeckDefinition, Eligibility, SHARED
from .models import StrictModel

FORMAT = 'edgeloop.character-package'
FORMAT_VERSION = 1
ROOT = 'character-builder'
IDENT = r'^[a-z0-9][a-z0-9-]{0,23}$'
CARD_LOCAL_ID = r'^[a-z0-9][a-z0-9-]{0,31}$'
THEME = r'^[a-z0-9][a-z0-9_-]{0,31}$'
SHORT_NAME = r"^[A-Z][A-Za-z'’-]{0,23}$"
MAX_CARDS = 16
MAX_ART_BYTES = 8 * 1024 * 1024
ART_TYPES = {b'\x89PNG\r\n\x1a\n': ('png', 'image/png'), b'\xff\xd8\xff': ('jpg', 'image/jpeg')}
# RIFF....WEBP is checked separately because the size sits between the two markers.
WEBP = ('webp', 'image/webp')
ART_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 _.-]{0,95}\.(?:png|jpe?g|webp)$', re.I)
STORED_ART = re.compile(r'^[0-9a-f]{64}\.(?:png|jpg|webp)$')
# The shared base the four built-in companions are layered on. Any installed chat model works.
DEFAULT_MODEL = 'huihui_ai/qwen3.5-abliterated:9b'

# Cards are dialogue briefs. A card that asks the companion to operate EdgeLoop belongs to the
# separate settings/action feature, which has an explicit, engine-authorized interface.
CONTROL_REQUEST = re.compile(
    r"\b(?:change|set|raise|lower|increase|decrease|adjust|switch|turn|speed|slow)\s+(?:\w+\s+){0,3}?"
    r"(?:the\s+)?(?:speed|intensity|stroke|strokes|mode|settings?|device|toy|machine|session|pause|stop|game|goal|level)\b"
    r"|\b(?:emergency\s+stop|stop the session|pause the session|end the session|start (?:a|the) session)\b", re.I)
# Characters are adults. Explicit minor descriptors are rejected rather than rewritten.
MINOR = re.compile(r"\b(?:child|children|kid|kids|minor|underage|under-age|teen|teenage[dr]?|teenager|"
                   r"schoolgirl|schoolboy|pre-?teen|adolescent|loli|shota|(?:1[0-7]|[1-9])[- ]?(?:years?|yrs?)[- ]old)\b", re.I)
# Text that would impersonate a prompt section or an engine message.
SECTION_MARKER = re.compile(r'(?m)^\s*(?:#{1,6}\s|SYSTEM\b|<\|?/?(?:im_start|im_end|system|user|assistant)\|?>|\[/?INST\])', re.I)


def clean_text(value):
    """Canonical text: LF line endings, no trailing spaces, no outer blank lines."""
    if not isinstance(value, str):
        return value
    value = value.replace('\r\n', '\n').replace('\r', '\n')
    return '\n'.join(line.rstrip() for line in value.strip().split('\n'))


class World(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=IDENT)
    name: str = Field(min_length=1, max_length=60)
    setting: str = Field(min_length=1, max_length=1200)
    lore: str = Field(default='', max_length=3000)
    rules: list[str] = Field(default_factory=list, max_length=8)

    @field_validator('name', 'setting', 'lore', mode='before')
    @classmethod
    def canonical_text(cls, value):
        return clean_text(value)

    @field_validator('rules', mode='before')
    @classmethod
    def clean_rules(cls, value):
        return [clean_text(rule) for rule in value] if isinstance(value, list) else value

    @field_validator('rules')
    @classmethod
    def rule_size(cls, value):
        if any(not rule or len(rule) > 200 or '\n' in rule for rule in value):
            raise ValueError('Each world rule is one line of 1 to 200 characters')
        return value


class Portrait(StrictModel):
    # A file name in the art inbox, never a path: no directories, no traversal.
    file: str = Field(min_length=5, max_length=100)
    fit: Literal['contain', 'cover'] = 'contain'
    position: str = Field(default='50% 50%', pattern=r'^(?:100|[1-9]?\d)% (?:100|[1-9]?\d)%$')

    @field_validator('file')
    @classmethod
    def plain_name(cls, value):
        if not ART_NAME.match(value) or '..' in value:
            raise ValueError('Use the file name of a PNG, JPEG or WebP image in the art folder, without any directory')
        return value


class CardSpec(StrictModel):
    """What the player writes. 'when' is the existing deck eligibility rule set."""
    id: str = Field(pattern=CARD_LOCAL_ID)
    theme: str = Field(pattern=THEME)
    brief: str = Field(min_length=1, max_length=400)
    occasion: str | None = Field(default=None, min_length=1, max_length=160)
    when: Eligibility = Field(default_factory=Eligibility)
    repeat: bool = True
    enabled: bool = True

    @field_validator('brief', 'occasion', mode='before')
    @classmethod
    def canonical_text(cls, value):
        return clean_text(value)

    @field_validator('brief', 'occasion')
    @classmethod
    def dialogue_only(cls, value):
        if value is not None and CONTROL_REQUEST.search(value):
            raise ValueError('Cards are dialogue and story briefs; a card cannot ask to change settings, '
                             'the device or the session (that needs the separate action interface)')
        if value is not None and SECTION_MARKER.search(value):
            raise ValueError('Card text cannot contain prompt section markers')
        return value


class DeckSpec(StrictModel):
    # 'lifecycle': the shared start, closing, arrival and milestone cards plus this deck.
    # 'lifecycle+routine': also the built-in shared routine cards (edge count, duration, heart rate).
    shared: Literal['lifecycle', 'lifecycle+routine'] = 'lifecycle'
    cards: list[CardSpec] = Field(default_factory=list, max_length=MAX_CARDS)

    @model_validator(mode='after')
    def unique(self):
        ids = [card.id for card in self.cards]
        if len(ids) != len(set(ids)):
            raise ValueError('Card IDs must be unique within the deck')
        return self


class Character(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(pattern=IDENT)
    revision: int = Field(default=1, ge=1)
    world: str = Field(pattern=IDENT)
    name: str = Field(min_length=1, max_length=60)
    short_name: str = Field(pattern=SHORT_NAME)
    age: int | None = Field(default=None, ge=18, le=1000)
    personality: str = Field(min_length=1, max_length=1200)
    voice: str = Field(min_length=1, max_length=800)
    relationship: str = Field(min_length=1, max_length=600)
    model: str = Field(default=DEFAULT_MODEL, min_length=1, max_length=120, pattern=r'^[a-zA-Z0-9_.:/-]+$')
    portrait: Portrait | None = None
    deck: DeckSpec = Field(default_factory=DeckSpec)

    @field_validator('name', 'personality', 'voice', 'relationship', mode='before')
    @classmethod
    def canonical_text(cls, value):
        return clean_text(value)

    @model_validator(mode='after')
    def adult(self):
        for field in ('name', 'personality', 'voice', 'relationship'):
            if MINOR.search(getattr(self, field)):
                raise ValueError(f'{field}: characters must be adults; remove descriptions of minors')
        return self


class BuilderError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('; '.join(f"{'.'.join(map(str, e['path'])) or 'package'}: {e['message']}" for e in errors))


def _errors(exc, prefix=()):
    result = []
    for item in exc.errors(include_url=False, include_context=False, include_input=False):
        message = item['msg'].removeprefix('Value error, ')
        result.append({'path': [*prefix, *item['loc']], 'message': message})
    return result


def validate_world(raw):
    try:
        return World.model_validate(raw), []
    except ValidationError as exc:
        return None, _errors(exc, ('world',))


def validate_character(raw):
    try:
        return Character.model_validate(raw), []
    except ValidationError as exc:
        return None, _errors(exc, ('character',))


def detect_art(data):
    for magic, kind in ART_TYPES.items():
        if data.startswith(magic):
            return kind
    if len(data) > 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return WEBP
    return None


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def persona_system(world, character):
    """The composed identity. Fixed wording, authored text in labelled fields only."""
    age = f' aged {character.age}' if character.age is not None else ''
    lines = [
        f'You are {character.name}, an adult{age} in a fictional world created by the participant.',
        f'Your name is {character.name}; use "{character.short_name}" as your short name.',
        'This world and this identity are complete in themselves: no other fictional world, organisation, '
        'place or character exists here unless this text names it.',
        '',
        f'World: {world.name}',
        f'Setting: {world.setting}',
    ]
    if world.lore:
        lines.append('Lore: ' + world.lore)
    if world.rules:
        lines.append('World rules:')
        lines += ['- ' + rule for rule in world.rules]
    lines += [
        '',
        f'Personality: {character.personality}',
        f'Voice: {character.voice}',
        f'Relationship to the participant: {character.relationship}',
        '',
        'Stay inside this world and this voice. The world shapes how you talk about things; it never '
        'changes the real session facts, which the application supplies separately.',
    ]
    return '\n'.join(lines)


def runtime_card(character, spec):
    return Card(id=f'{character.id}.{spec.id}', kind='normal', audience=identity(character.id),
                intent=spec.theme.replace('-', '_'), brief=spec.brief, occasion=spec.occasion,
                eligibility=spec.when, memory='none', repeat=spec.repeat)


def identity(character_id):
    return 'custom.' + character_id


def compose(world, character, art=None):
    """Pure Character Composer: same inputs, same package bytes and content hash.

    art: (bytes) of the portrait, or None. Raises BuilderError with every problem found.
    """
    errors = []
    if not isinstance(world, World):
        world, problems = validate_world(world)
        errors += problems
    if not isinstance(character, Character):
        character, problems = validate_character(character)
        errors += problems
    if errors:
        raise BuilderError(errors)
    if character.world != world.id:
        errors.append({'path': ['character', 'world'], 'message': f'Character uses world "{character.world}", not "{world.id}"'})
    for index, rule in enumerate(world.rules):
        if SECTION_MARKER.search(rule):
            errors.append({'path': ['world', 'rules', index], 'message': 'World text cannot contain prompt section markers'})
    for field in ('setting', 'lore'):
        if SECTION_MARKER.search(getattr(world, field)):
            errors.append({'path': ['world', field], 'message': 'World text cannot contain prompt section markers'})
        if MINOR.search(getattr(world, field)):
            errors.append({'path': ['world', field], 'message': 'Worlds may not describe minors in this adult app'})
    portrait = None
    if character.portrait is not None:
        if art is None:
            errors.append({'path': ['character', 'portrait', 'file'], 'message': f'Portrait "{character.portrait.file}" was not found in the art folder'})
        elif len(art) > MAX_ART_BYTES:
            errors.append({'path': ['character', 'portrait', 'file'], 'message': 'Portrait is larger than 8 MB'})
        elif (kind := detect_art(art)) is None:
            errors.append({'path': ['character', 'portrait', 'file'], 'message': 'Portrait is not a PNG, JPEG or WebP image'})
        else:
            digest = sha256(art).hexdigest()
            portrait = {'sha256': digest, 'file': f'{digest}.{kind[0]}', 'media_type': kind[1],
                        'fit': character.portrait.fit, 'position': character.portrait.position}
    enabled = sorted((c for c in character.deck.cards if c.enabled), key=lambda c: c.id)
    if not enabled:
        errors.append({'path': ['character', 'deck', 'cards'], 'message': 'Enable at least one card'})
    if errors:
        raise BuilderError(errors)
    cards = [runtime_card(character, spec).model_dump(mode='json', exclude_defaults=False) for spec in enabled]
    body = {
        'format': FORMAT, 'format_version': FORMAT_VERSION,
        'id': character.id, 'revision': character.revision, 'identity': identity(character.id),
        'model': character.model,
        'world': world.model_dump(mode='json'),
        'character': {k: v for k, v in character.model_dump(mode='json').items() if k not in {'deck', 'portrait', 'model', 'revision', 'world'}} | {'world': world.id},
        'portrait': portrait,
        'persona_system': persona_system(world, character),
        'deck': {'shared': character.deck.shared, 'cards': cards},
    }
    body['content_sha256'] = sha256(canonical(body).encode()).hexdigest()
    return body


def package_bytes(package):
    return (canonical(package) + '\n').encode()


class Package(StrictModel):
    """Loader-side check of a stored package; recomputes the hash, so edits are detected."""
    format: Literal['edgeloop.character-package']
    format_version: Literal[1]
    id: str = Field(pattern=IDENT)
    revision: int = Field(ge=1)
    identity: str
    model: str = Field(min_length=1, max_length=120, pattern=r'^[a-zA-Z0-9_.:/-]+$')
    world: World
    character: dict
    portrait: dict | None
    persona_system: str = Field(min_length=1, max_length=12000)
    deck: dict
    content_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def consistent(self):
        if self.identity != identity(self.id):
            raise ValueError('Package identity does not match its ID')
        cards = [Card.model_validate(card) for card in self.deck.get('cards', [])]
        if not cards or any(c.kind != 'normal' or c.audience != self.identity or not c.id.startswith(self.id + '.') for c in cards):
            raise ValueError('Package cards must be custom normal cards for this character only')
        if self.deck.get('shared') not in {'lifecycle', 'lifecycle+routine'}:
            raise ValueError('Unknown shared-card policy')
        return self

    @property
    def cards(self):
        return [Card.model_validate(card) for card in self.deck['cards']]

    @property
    def short_name(self):
        return self.character['short_name']

    @property
    def display_name(self):
        return self.character['name']


def load_package(raw):
    try:
        package = Package.model_validate(raw)
    except (ValidationError, ValueError, TypeError) as exc:
        raise BuilderError([{'path': ['package'], 'message': 'Invalid character package: ' + str(exc).splitlines()[0][:200]}]) from None
    body = {k: v for k, v in raw.items() if k != 'content_sha256'}
    if sha256(canonical(body).encode()).hexdigest() != package.content_sha256:
        raise BuilderError([{'path': ['package', 'content_sha256'], 'message': 'Package content does not match its hash; it was edited after composing'}])
    return package


def compose_definition(base, package):
    """Shared lifecycle cards from the built-in deck, plus this character's own deck.

    The built-in companions' personal cards never reach a custom character, and its cards
    never reach them, because every custom card's audience is the custom identity.
    """
    shared = lambda cards: [c for c in cards if c.audience == SHARED]
    normal = shared(base.normal) if package.deck['shared'] == 'lifecycle+routine' else []
    return DeckDefinition(revision=base.revision, session_start=shared(base.session_start),
                          session_end=shared(base.session_end), arrival=shared(base.arrival),
                          sequences=[s for s in base.sequences if s.audience == SHARED],
                          normal=normal + package.cards)


ELIGIBILITY_WORDS = {
    'min_seconds': 'after {} s', 'max_seconds': 'until {} s', 'min_edges': 'from edge {}', 'max_edges': 'up to edge {}',
}


def describe_when(rule):
    words = [ELIGIBILITY_WORDS[k].format(getattr(rule, k)) for k in ELIGIBILITY_WORDS if getattr(rule, k) is not None]
    if rule.requires_hr:
        words.append('needs live heart rate' + (' (' + '/'.join(rule.hr_trends) + ')' if rule.hr_trends else ''))
    if rule.requires_conversation:
        words.append('after the participant has talked')
    if rule.requires_story_welcome:
        words.append('when story is welcome')
    if rule.statuses != ['RUNNING', 'RAMPDOWN']:
        words.append('only ' + '/'.join(s.lower() for s in rule.statuses))
    return ', '.join(words) or 'any time during a running session'


class Library:
    """File-backed sources, art and packages under the observer's data directory."""

    def __init__(self, store):
        self.store = store
        self.root = Path(store.root) / ROOT

    @property
    def art_inbox(self):
        return self.root / 'art'

    def _path(self, kind, ident):
        if not re.match(IDENT, ident or ''):
            raise BuilderError([{'path': [kind, 'id'], 'message': 'Invalid ID'}])
        return f'{ROOT}/{kind}/{ident}.json'

    def list(self):
        def names(kind):
            folder = self.root / kind
            return sorted(p.stem for p in folder.glob('*.json') if re.match(IDENT, p.stem)) if folder.is_dir() else []
        self.art_inbox.mkdir(parents=True, exist_ok=True)
        art = sorted(p.name for p in self.art_inbox.iterdir() if p.is_file() and ART_NAME.match(p.name))
        return {'worlds': names('worlds'), 'characters': names('characters'), 'art': art,
                'art_folder': str(self.art_inbox), 'active': self.active()}

    def read(self, kind, ident):
        raw = self.store.read(self._path(kind, ident))
        if raw is None:
            raise BuilderError([{'path': [kind[:-1]], 'message': f'No saved {kind[:-1]} "{ident}"'}])
        return raw

    def save_world(self, raw):
        world, errors = validate_world(raw)
        if errors:
            raise BuilderError(errors)
        self.store.write(self._path('worlds', world.id), world.model_dump(mode='json'))
        return world

    def save_character(self, raw):
        character, errors = validate_character(raw)
        if errors:
            raise BuilderError(errors)
        previous = self.store.read(self._path('characters', character.id))
        # Each save that changes the content is a new revision; the player never manages it.
        if previous and {k: v for k, v in previous.items() if k != 'revision'} != {k: v for k, v in character.model_dump(mode='json').items() if k != 'revision'}:
            character = character.model_copy(update={'revision': int(previous.get('revision', 1)) + 1})
        elif previous:
            character = character.model_copy(update={'revision': int(previous.get('revision', 1))})
        self.store.write(self._path('characters', character.id), character.model_dump(mode='json'))
        return character

    def art(self, name):
        if not ART_NAME.match(name or '') or '..' in name:
            return None
        path = self.art_inbox / name
        try:
            if path.is_symlink() or not path.is_file() or path.resolve().parent != self.art_inbox.resolve():
                return None
            if path.stat().st_size > MAX_ART_BYTES:
                return b'\0' * (MAX_ART_BYTES + 1)
            return path.read_bytes()
        except OSError:
            return None

    def compose(self, character_id):
        """Compose from saved sources and stage the portrait. Raises BuilderError."""
        character, errors = validate_character(self.read('characters', character_id))
        if errors:
            raise BuilderError(errors)
        world = self.read('worlds', character.world) if (self.root / 'worlds' / f'{character.world}.json').exists() else None
        if world is None:
            raise BuilderError([{'path': ['character', 'world'], 'message': f'World "{character.world}" has not been saved'}])
        art = self.art(character.portrait.file) if character.portrait else None
        package = compose(world, character, art)
        if package['portrait']:
            store = self.root / 'art-store'
            store.mkdir(parents=True, exist_ok=True)
            target = store / package['portrait']['file']
            if not target.exists():
                temporary = target.with_suffix('.tmp')
                temporary.write_bytes(art)
                temporary.replace(target)
        return package

    def write_package(self, package):
        name = f"{ROOT}/packages/{package['id']}/{package['content_sha256'][:12]}.json"
        self.store.write(name, package)
        return name

    def load(self, character_id, digest):
        if not re.match(IDENT, character_id or '') or not re.match(r'^[0-9a-f]{64}$', digest or ''):
            raise BuilderError([{'path': ['active'], 'message': 'Invalid active package reference'}])
        raw = self.store.read(f'{ROOT}/packages/{character_id}/{digest[:12]}.json')
        if raw is None:
            raise BuilderError([{'path': ['active'], 'message': 'The activated package is missing'}])
        package = load_package(raw)
        if package.content_sha256 != digest:
            raise BuilderError([{'path': ['active'], 'message': 'The activated package was replaced'}])
        return package

    def active(self):
        return self.store.read(f'{ROOT}/active.json')

    def set_active(self, package):
        self.store.write(f'{ROOT}/active.json', None if package is None else
                         {'id': package.id, 'content_sha256': package.content_sha256, 'model': package.model})

    def stored_art(self, name):
        if not STORED_ART.match(name or ''):
            return None
        path = self.root / 'art-store' / name
        try:
            data = path.read_bytes()
        except OSError:
            return None
        # Only bytes that still hash to their name and are still the image type the composer stored.
        if sha256(data).hexdigest() != name.split('.')[0] or (detect_art(data) or ('',))[0] != name.rsplit('.', 1)[1]:
            return None
        return data


def preview(package, base_definition):
    """What activation would do, without doing it."""
    from .event_deck import shuffled
    definition = compose_definition(base_definition, Package.model_validate(package))
    visible = [c for c in definition.normal if c.audience in {SHARED, package['identity']}]
    themes = {}
    for card in visible:
        themes[card.intent] = themes.get(card.intent, 0) + 1
    order = shuffled([c.id for c in visible], package['content_sha256'])
    return {
        'id': package['id'], 'revision': package['revision'], 'content_sha256': package['content_sha256'],
        'model': package['model'], 'name': package['character']['name'], 'short_name': package['character']['short_name'],
        'world': package['world']['name'], 'persona_system': package['persona_system'],
        'persona_characters': len(package['persona_system']),
        'portrait': package['portrait'],
        'cards': [{'id': c.id, 'theme': c.intent, 'brief': c.brief, 'occasion': c.occasion, 'when': describe_when(c.eligibility),
                   'custom': c.audience != SHARED} for c in visible],
        'themes': dict(sorted(themes.items())),
        'shared_lifecycle': {'session_start': [c.id for c in definition.session_start], 'session_end': [c.id for c in definition.session_end],
                             'arrival': [c.id for c in definition.arrival], 'milestones': [s.id for s in definition.sequences]},
        'sample_shuffle': order,
    }
