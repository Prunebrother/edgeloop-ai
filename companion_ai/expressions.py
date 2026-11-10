# SPDX-License-Identifier: AGPL-3.0-only
"""Version 1 presentation envelope. Never accepts user text or session commands."""
import re

EXPRESSIONS = ('neutral', 'happy', 'playful', 'flirty', 'mischievous', 'focused',
               'excited', 'surprised', 'disappointed', 'concerned', 'proud', 'comforting')
FORMAT_INSTRUCTION = (
    'Output format v1: begin your reply with exactly one [[expression:ID]] header. '
    'The word expression is literal. ID is one allowed identifier, never a number. '
    'Choose ID from: ' + ', '.join(EXPRESSIONS) + '. '
    'Then give your normal dialogue in your established character. '
    'Choose the expression for the delivery of this particular reply; do not copy an earlier header mechanically. The header describes your intended delivery, never the user or session state. '
    'Do not explain the header or narrate a facial gesture for this format.')
# Near-miss IDs the F29 models write in place of an allowed one (counted over the 2026-11 simulation runs:
# curious 44, confident 36, pride 8, thoughtful 6, ...). The portrait shows the closest allowed expression.
ALIASES = {
    'curious': 'focused', 'intrigued': 'focused', 'thoughtful': 'focused', 'practical': 'focused', 'analytical': 'focused',
    'determined': 'focused', 'serious': 'focused', 'attentive': 'focused', 'clinical': 'focused',
    'confident': 'proud', 'pride': 'proud', 'prideful': 'proud', 'smug': 'proud', 'satisfied': 'proud', 'triumphant': 'proud',
    'impressed': 'proud',
    'content': 'happy', 'hopeful': 'happy', 'pleased': 'happy', 'delighted': 'happy', 'cheerful': 'happy', 'warm': 'happy',
    'amused': 'playful', 'teasing': 'playful', 'cheeky': 'mischievous', 'bratty': 'mischievous', 'sly': 'mischievous',
    'seductive': 'flirty', 'sultry': 'flirty', 'coy': 'flirty', 'sensual': 'flirty',
    'eager': 'excited', 'thrilled': 'excited', 'enthusiastic': 'excited',
    'shocked': 'surprised', 'astonished': 'surprised', 'amazed': 'surprised',
    'sad': 'disappointed', 'frustrated': 'disappointed',
    'worried': 'concerned', 'anxious': 'concerned', 'cautious': 'concerned',
    'reassuring': 'comforting', 'gentle': 'comforting', 'caring': 'comforting', 'soothing': 'comforting', 'tender': 'comforting',
    'composed': 'neutral', 'calm': 'neutral',
}


def resolve_expression(content):
    """The allowed ID a leading header means, or None. Accepts the canonical [[expression:ID]], a near-miss
    ID ([[expression:curious]] -> focused), any letter case, and the bare [[ID:anything]] form ([[happy:125]])."""
    content = content.strip().lower()
    if content.startswith('expression:'):
        word = content.removeprefix('expression:').strip()
    else:
        word = content.split(':', 1)[0].strip()
        if word not in EXPRESSIONS:
            return None
    return word if word in EXPRESSIONS else ALIASES.get(word)


# Repeats the contract at the start of a short card prompt, where this model otherwise malforms it.
HEADER_REMINDER = 'Begin with the [[expression:ID]] header, with ID from the allowed list.'
_IDS = '|'.join(EXPRESSIONS)
# One-bracket lookalikes of the header, on card turns only. At the start of a reply they stand where the
# header belongs. Further in, only the unmistakable forms count, so "He looked [proud] of it." stays visible.
_SINGLE_BRACKET_TAG = re.compile(rf'\[\s*(?:expression\s*:\s*)?(?:{_IDS})\s*(?::[^\]\n]*)?\]', re.I)
_INLINE_TAG = re.compile(rf'\[\s*(?:expression\s*:[^\]\n]*|(?:{_IDS})\s*:\S*)\s*\]', re.I)
_SINGLE_BRACKET_LIMIT = 48


def _is_bare_id(content):
    return content.strip().lower() in EXPRESSIONS


class ExpressionStream:
    """Version 1 scanner; at most 64 envelope characters plus a token prefix.

    Double-bracket envelopes containing a colon are reserved presentation data.
    Only the canonical leading expression header is accepted. Malformed envelopes
    are removed, never translated into another protocol. Ordinary [[prose]] and [prose]
    are preserved. Legacy inline reasoning is suppressed independently.

    `card` is for the Director's own turns, where a model malforms the header it was just
    reminded of: a leading [[happy]], [happy] or [happy:Daisy] goes as well.
    """
    tokens = ('[[', '<think>', '</think>')

    def __init__(self, on_expression=None, enabled=True, card=False):
        self.pending = ''
        self.mode = 'text'
        self.envelope = ''
        self.tail = ''
        self.oversized = False
        self.expression = None
        self.candidate = None
        self.valid = None
        self.leading = True
        self.headers = 0
        self.on_expression = on_expression
        self.enabled = enabled
        self.card = card

    def _bare_header(self, content):
        return self.card and self.leading and _is_bare_id(content)

    def _lookalike(self, tag):
        return (_SINGLE_BRACKET_TAG if self.leading else _INLINE_TAG).fullmatch(tag)

    def _envelope_end(self, closed):
        content = self.envelope[:-2] if closed else self.envelope.rstrip('\n')
        reserved = self.oversized or ':' in content or content.startswith('expression') or self._bare_header(content)
        if not reserved:
            self.leading = False
            return '[[' + self.envelope
        self.headers += 1
        candidate = content.removeprefix('expression:').strip().lower()
        resolved = resolve_expression(content) if closed and not self.oversized else None
        if self.headers == 1:
            self.candidate = candidate if not self.oversized and 0<len(candidate)<=32 and all(c in 'abcdefghijklmnopqrstuvwxyz_:0123456789' for c in candidate) else None
            self.valid = resolved is not None
            if resolved and self.leading and self.enabled:
                self.expression = resolved
                if self.on_expression:self.on_expression(resolved)
        return ''

    def feed(self, text):
        output = []
        for char in text:
            if self.mode == 'metadata':
                self.tail = (self.tail + char)[-2:]
                if len(self.envelope) < 64:self.envelope += char
                else:
                    if ':' not in self.envelope and not self.envelope.startswith('expression'):
                        output.append('[[' + self.envelope + char)
                        self.envelope='';self.mode='text';self.leading=False;self.tail=''
                        continue
                    self.oversized = True
                if self.tail == ']]' or char == '\n':
                    output.append(self._envelope_end(self.tail == ']]'))
                    self.mode = 'text';self.envelope = '';self.tail = '';self.oversized = False
                continue
            if self.mode == 'reasoning':
                self.tail = (self.tail + char)[-8:]
                if self.tail.lower().endswith('</think>'):
                    self.mode = 'text';self.tail = ''
                continue
            self.pending += char
            while self.pending:
                lower = self.pending.lower()
                if lower == '[[':
                    self.mode = 'metadata';self.pending = '';self.envelope = '';self.tail = ''
                    break
                if lower == '<think>':
                    self.mode = 'reasoning';self.pending = '';self.tail = ''
                    break
                if lower == '</think>':
                    self.pending = '';break
                if any(token.startswith(lower) for token in self.tokens):break
                if self.card and self.pending[0] == '[':
                    closing = self.pending.find(']')
                    if closing < 0 and len(self.pending) < _SINGLE_BRACKET_LIMIT and '\n' not in self.pending:break
                    if closing >= 0 and self._lookalike(self.pending[:closing + 1]):
                        self.pending = self.pending[closing + 1:]
                        continue
                visible = self.pending[0];self.pending = self.pending[1:]
                output.append(visible)
                if not visible.isspace():self.leading = False
        return ''.join(output)

    def finish(self):
        # Never release a truncated reserved prefix. Retain ordinary bracket prose.
        remainder=self.pending if self.pending in {'[','<'} else ''
        if self.card and self.pending.startswith('[') and not self.pending.startswith('[['):
            word=re.split(r'[:\]]',self.pending[1:].lower(),maxsplit=1)[0].strip()
            truncated_tag=word=='expression' or word in EXPRESSIONS and (self.leading or ':' in self.pending)
            if not truncated_tag:remainder=self.pending
        self.pending = ''
        if self.mode == 'metadata':
            content = self.envelope
            if not self.oversized and ':' not in content and not 'expression'.startswith(content) and not content.startswith('expression') and not (self.card and _is_bare_id(content)):
                return '[[' + content
            self.valid = False
        return remainder


def clean_dialogue(text):
    parser = ExpressionStream(enabled=False)
    return (parser.feed(text) + parser.finish()).strip()
