import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { speakPrompt, speakNow, cancelSpeech, speechHooks } from './voice.js';

describe('spoken cues call speechSynthesis', () => {
    let spoken;
    let orig;

    beforeEach(() => {
        spoken = [];
        orig = { getSynth: speechHooks.getSynth, UtteranceCtor: speechHooks.UtteranceCtor };
        class FakeUtterance {
            constructor(text) {
                this.text = text;
            }
        }
        const synth = {
            speak(utterance) {
                spoken.push(utterance.text);
                if (typeof utterance.onend === 'function') queueMicrotask(() => utterance.onend());
            },
            cancel() {},
            getVoices() { return []; }
        };
        speechHooks.getSynth = () => synth;
        speechHooks.UtteranceCtor = () => FakeUtterance;
    });

    afterEach(() => {
        cancelSpeech();
        speechHooks.getSynth = orig.getSynth;
        speechHooks.UtteranceCtor = orig.UtteranceCtor;
    });

    it('speakPrompt speaks the cue when enabled', () => {
        speakPrompt(true, 'Session started. Breathe.');
        assert.deepEqual(spoken, ['Session started. Breathe.']);
    });

    it('speakPrompt stays silent when disabled or empty', () => {
        speakPrompt(false, 'Nope.');
        speakPrompt(true, '');
        assert.deepEqual(spoken, []);
    });

    it('speakNow jumps the queue and still speaks', async () => {
        speakPrompt(true, 'one');
        speakNow('Heart rate signal lost. Motors stopped.');
        await new Promise((resolve) => setTimeout(resolve, 80));
        assert.ok(spoken.includes('Heart rate signal lost. Motors stopped.'));
    });
});
