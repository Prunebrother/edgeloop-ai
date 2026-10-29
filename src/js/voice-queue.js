// Pure queue logic behind the spoken cues (voice.js owns speechSynthesis).
//
// Rules: a cue identical to the one currently speaking or to the last cue
// waiting is dropped; the queue holds at most `maxQueued` cues and drops the
// OLDEST when full; `jump` (safety-critical cues) discards everything
// waiting and becomes the current cue at once; `clear` silences all.
export const DEFAULT_MAX_QUEUED = 3;

export function createCueQueue({ maxQueued = DEFAULT_MAX_QUEUED } = {}) {
    const limit = Number.isFinite(maxQueued) && maxQueued >= 1 ? Math.floor(maxQueued) : DEFAULT_MAX_QUEUED;
    let current = null;
    const queued = [];

    return {
        get current() {
            return current;
        },
        get queued() {
            return [...queued];
        },
        isIdle() {
            return current === null;
        },
        // Returns true when the cue was accepted (the caller then starts
        // speaking if the queue was idle).
        enqueue(text) {
            if (typeof text !== 'string' || !text) return false;
            if (current === text) return false;
            if (queued.length > 0 && queued[queued.length - 1] === text) return false;
            queued.push(text);
            while (queued.length > limit) queued.shift();
            return true;
        },
        // Safety-critical cue: everything waiting is dropped and `text`
        // becomes the current cue immediately. Returns the text to speak.
        jump(text) {
            if (typeof text !== 'string' || !text) return null;
            queued.length = 0;
            current = text;
            return text;
        },
        // The current cue finished: promote the next one (or go idle).
        // Returns the cue to speak now, or null when nothing is waiting.
        next() {
            current = queued.length > 0 ? queued.shift() : null;
            return current;
        },
        clear() {
            queued.length = 0;
            current = null;
        }
    };
}
