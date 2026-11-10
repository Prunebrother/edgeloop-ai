"""Deterministic cleanup of model habits in visible replies: wrapping quotes with narration,
re-stating the participant's message, and over-long replies.

One character-level state machine serves both the stream and the final text, so the
streamed deltas always equal the stored reply regardless of chunk boundaries."""
from dataclasses import dataclass
import re

QUOTES = '"“”'
TERMINATORS = '.!?…'
ABBREVIATIONS = {'mr', 'mrs', 'ms', 'dr', 'st', 'vs', 'etc', 'e.g', 'i.e', 'jr', 'sr', 'prof'}
# The participant's first person is the companion's second person.
SWAP = {'i': 'you', "i'm": "you're", 'im': "you're", 'me': 'you', 'my': 'your', 'mine': 'yours', 'myself': 'yourself',
        "i've": "you've", "i'll": "you'll", "i'd": "you'd", 'am': 'are', 'was': 'were'}


@dataclass(frozen=True)
class CleanupConfig:
    enabled: bool = True
    unwrap_quotes: bool = True
    strip_echo: bool = True
    max_echo_sentences: int = 2
    echo_overlap: float = 0.75
    user_max_characters: int = 600
    card_max_characters: int = 400


# After an echoed quote that ends mid-sentence ("…," you said, and …) only a tail that opens with an
# attribution is dropped. Anything else ("…," I raised the intensity.) is the real answer and is kept.
SPEAKERS = {'you', 'u', 'he', 'she', 'they', 'i', 'we'}
SPEECH_VERBS = {'said', 'say', 'says', 'saying', 'asked', 'ask', 'asks', 'asking', 'begged', 'beg', 'begs', 'begging',
                'told', 'tell', 'tells', 'whispered', 'whisper', 'moaned', 'moan', 'groaned', 'gasped', 'panted', 'pleaded',
                'plead', 'insisted', 'claimed', 'demanded', 'typed', 'wrote', 'write', 'murmured', 'breathed', 'sighed',
                'growled', 'purred', 'boasted', 'bragged', 'announced', 'declared', 'promised', 'swore', 'called', 'cried'}


def _attribution(words):
    """True/False once the opening words decide it, None while more words are needed."""
    words = [w.strip(',.!?;:…' + QUOTES + "'").lower() for w in words]
    words = [w for w in words if w]
    if not words:
        return None
    if words[0] in SPEECH_VERBS:
        return True
    if words[0] not in SPEAKERS:
        return False
    if len(words) < 2:
        return None
    return words[1] in SPEECH_VERBS


def _words(text):
    return re.findall(r"[a-z0-9']+", text.casefold().replace('’', "'"))


def _sentences(text):
    return [s for s in re.split(r'(?<=[.!?…])\s+', text.strip()) if s]


def _is_question(sentence):
    return sentence.rstrip(' ' + QUOTES + "')").endswith('?')


def _echo_texts(echo):
    """One message or several (the current and the previous participant message)."""
    if not echo:
        return []
    return [echo] if isinstance(echo, str) else [e for e in echo if e]


def _echo_targets(echo):
    targets = []
    for sentence in (s for text in _echo_texts(echo) for s in _sentences(text)):
        words = _words(sentence)
        targets.append((_is_question(sentence), set(words) | {SWAP.get(w, w) for w in words}))
    return targets


def is_echo(sentence, targets, overlap=0.75):
    """A leading sentence that re-states the participant: same kind, mostly their words."""
    words = _words(sentence)
    if len(words) < 3:
        return False
    question = _is_question(sentence)
    return any(kind == question and sum(w in vocabulary for w in words) / len(words) >= overlap for kind, vocabulary in targets)


class ReplyCleaner:
    def __init__(self, echo=None, max_characters=None, config=CleanupConfig()):
        self.config = config
        self.targets = _echo_targets(echo) if config.strip_echo else []
        # An opening quoted segment is held back until it is known not to be an echo.
        self.hold_limit = 2 * max((len(t) for t in _echo_texts(echo)), default=0) + 20 if self.targets else 0
        self.holding = False
        self.held = ''
        self.skipping = False     # dropping the rest of the sentence an echoed quote opened ("…," you said, and)
        self.skipped = ''
        self.attributed = None    # whether that rest opens with an attribution, once its first words are in
        self.max_characters = max_characters
        self.started = False      # first non-space character seen
        self.quoted = False       # reply opened with a quote: keep only speech inside quotes
        self.inside = False
        self.joined = False       # a gap between speech segments needs one space
        self.sentence = ''        # current, not yet released sentence (head stage) or held whitespace
        self.head = True          # still deciding whether leading sentences are echoes
        self.dropped = []
        self.echoes = 0
        self.emitted = 0
        self.over = False         # past the cap: finish the current sentence, then stop
        self.stopped = False
        self.pending_end = False  # saw terminator + space; the next visible character decides
        self.recent = ''          # tail of the text seen, released or not, for sentence-end checks
        self.out = []

    # -- speech filter -------------------------------------------------
    def feed(self, chunk):
        self.out = []
        for char in chunk:
            self._speech_char(char)
        return ''.join(self.out)

    def finish(self):
        self.out = []
        if self.holding:
            self._decide_quote(closed=False)
        if self.skipping and self.skipped.strip():
            if _attribution(self.skipped.split()) is False:
                self._unskip()
            else:
                self.skipping = False
                self.dropped[-1] += ' ' + self.skipped.strip()
        self._close_sentence(final=True)
        if not self.emitted and self.dropped:  # never reduce a reply to nothing
            self._emit(' '.join(self.dropped))
        return ''.join(self.out)

    def _speech_char(self, char):
        if not self.config.enabled:
            self.out.append(char)
            return
        if not self.started:
            if char.isspace():
                return
            self.started = True
            if self.config.unwrap_quotes and char in QUOTES:
                self.quoted = self.inside = True
                self.holding = bool(self.hold_limit)
                return
        if self.skipping:
            self._skip_char(char)
            return
        if self.holding:
            if char in QUOTES:
                self._decide_quote(closed=True)
                return
            self.held += char
            if len(self.held) > self.hold_limit:
                self._decide_quote(closed=False, may_echo=False)
            return
        if self.quoted:
            if char in QUOTES:
                self.inside = not self.inside
                if not self.inside:
                    self.joined = True
                return
            if not self.inside:
                return
            if self.joined:
                self.joined = False
                self._text_char(' ')
        self._text_char(char)

    def _decide_quote(self, closed, may_echo=True):
        """The opening quote closed (or grew too long). A quote that only re-states the participant is
        dropped and the reply continues as unquoted text; anything else is speech as before."""
        self.holding = False
        held, self.held = self.held, ''
        sentences = _sentences(held)
        if may_echo and sentences and self.echoes < self.config.max_echo_sentences and \
                all(is_echo(s, self.targets, self.config.echo_overlap) for s in sentences):
            self.echoes += 1
            self.quoted = self.inside = False
            self.dropped.append(held.strip())
            core = held.rstrip()
            self.skipping = not core or core[-1] not in TERMINATORS
            self.skipped = ''
            self.attributed = None
            return
        for char in held:
            self._text_char(char)
        if closed:  # later speech segments are joined with a space, as before
            self.inside = False
            self.joined = True

    def _skip_char(self, char):
        if char.isspace() and self.skipped.rstrip(QUOTES + ')\'')[-1:] in tuple(TERMINATORS):
            self.skipping = False
            self.dropped[-1] += ' ' + self.skipped.strip()
            return
        if self.attributed is None and char.isspace() and self.skipped.strip():
            self.attributed = _attribution(self.skipped.split())
            if self.attributed is False:
                self._unskip()
                self._speech_char(char)
                return
        self.skipped += char

    def _unskip(self):
        """The text after the echo is not an attribution: it is the answer, so it goes out as ordinary text."""
        self.skipping = False
        held, self.skipped = self.skipped, ''
        for char in held:
            self._speech_char(char)

    # -- sentence stage ------------------------------------------------
    def _text_char(self, char):
        if self.stopped:
            return
        if self.pending_end:
            if char.isspace():
                self.sentence += char
                return
            if char.isupper() or char.isdigit() or char in QUOTES or char in "'(":
                self._close_sentence()
                if self.stopped:
                    return
            self.pending_end = False
        self.sentence += char
        self.recent = (self.recent + char)[-24:]
        if char.isspace() and self._ends_sentence(self.recent.rstrip()):
            self.pending_end = True
            return
        if not self.head and not char.isspace():
            self._release()

    def _ends_sentence(self, text):
        if not text or text[-1] not in TERMINATORS + QUOTES + ')':
            return False
        core = text.rstrip(QUOTES + ')\'')
        if not core or core[-1] not in TERMINATORS:
            return False
        word = re.findall(r"([A-Za-z.]+)\.$", core)
        return not (core.endswith('.') and word and word[0].casefold().rstrip('.') in ABBREVIATIONS)

    def _close_sentence(self, final=False):
        self.pending_end = False
        text = self.sentence
        if self.head:
            if not text.strip():
                return
            self.recent = ''
            self.sentence = ''
            if self.echoes < self.config.max_echo_sentences and is_echo(text, self.targets, self.config.echo_overlap):
                self.echoes += 1
                self.dropped.append(text.strip())
                return
            self.head = False
            self._emit(text.strip() if final else text.lstrip())
        else:
            self._release(final)
        if self.over and not final:
            self.stopped = True
            self.sentence = ''

    def _release(self, final=False):
        text, self.sentence = self.sentence, ''
        self._emit(text.rstrip() if final else text)

    def _emit(self, text):
        if not text:
            return
        if self.emitted == 0:
            text = text.lstrip()
            text = text[:1].upper() + text[1:]
        self.out.append(text)
        self.emitted += len(text)
        if self.max_characters and self.emitted >= self.max_characters:
            self.over = True


def clean_reply(text, echo=None, max_characters=None, config=CleanupConfig()):
    cleaner = ReplyCleaner(echo, max_characters, config)
    return (cleaner.feed(text) + cleaner.finish()).strip()
