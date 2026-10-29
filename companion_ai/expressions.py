# SPDX-License-Identifier: AGPL-3.0-only
"""Version 1 presentation envelope. Never accepts user text or session commands."""
EXPRESSIONS = ('neutral', 'happy', 'playful', 'flirty', 'mischievous', 'focused',
               'excited', 'surprised', 'disappointed', 'concerned', 'proud', 'comforting')
FORMAT_INSTRUCTION = (
    'Output format v1: begin your reply with exactly one [[expression:ID]] header. '
    'The word expression is literal. ID is one allowed identifier, never a number. '
    'Choose ID from: ' + ', '.join(EXPRESSIONS) + '. '
    'Then give your normal dialogue in your established character. '
    'Choose the expression for the delivery of this particular reply; do not copy an earlier header mechanically. The header describes your intended delivery, never the user or session state. '
    'Do not explain the header or narrate a facial gesture for this format.')


class ExpressionStream:
    """Version 1 scanner; at most 64 envelope characters plus a token prefix.

    Double-bracket envelopes containing a colon are reserved presentation data.
    Only the canonical leading expression header is accepted. Malformed envelopes
    are removed, never translated into another protocol. Ordinary [[prose]] is
    preserved. Legacy inline reasoning is suppressed independently.
    """
    tokens = ('[[', '<think>', '</think>')

    def __init__(self, on_expression=None, enabled=True):
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

    def _envelope_end(self, closed):
        content = self.envelope[:-2] if closed else self.envelope.rstrip('\n')
        reserved = self.oversized or ':' in content or content.startswith('expression')
        if not reserved:
            self.leading = False
            return '[[' + self.envelope
        self.headers += 1
        candidate = content.removeprefix('expression:')
        valid = closed and not self.oversized and content.startswith('expression:') and candidate in EXPRESSIONS
        if self.headers == 1:
            self.candidate = candidate if not self.oversized and 0<len(candidate)<=32 and all(c in 'abcdefghijklmnopqrstuvwxyz_' for c in candidate) else None
            self.valid = valid
            if valid and self.leading and self.enabled:
                self.expression = candidate
                if self.on_expression:self.on_expression(candidate)
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
                visible = self.pending[0];self.pending = self.pending[1:]
                output.append(visible)
                if not visible.isspace():self.leading = False
        return ''.join(output)

    def finish(self):
        # Never release a truncated reserved prefix. Retain ordinary bracket prose.
        remainder=self.pending if self.pending in {'[','<'} else ''
        self.pending = ''
        if self.mode == 'metadata':
            content = self.envelope
            if not self.oversized and ':' not in content and not 'expression'.startswith(content) and not content.startswith('expression'):
                return '[[' + content
            self.valid = False
        return remainder


def clean_dialogue(text):
    parser = ExpressionStream(enabled=False)
    return (parser.feed(text) + parser.finish()).strip()
