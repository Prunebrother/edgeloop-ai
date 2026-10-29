// Coalesced settings writes. Typing into a Session Setup field updates the
// settings object on the spot - the engine reads it from memory on the next
// tick, so a mid-session correction takes effect on the keystroke - but the
// STORE write does not have to happen once per key: the whole settings blob
// (voice banks and learning profile included) is JSON-encoded on every one.
//
// This schedules at most one write per window instead. Two rules keep it
// safe, because the point of storing these values is that a reload gets them
// back:
//   * the window is a CEILING, not a debounce: the timer is armed by the
//     first unwritten edit and never pushed back by later ones, so held-down
//     keys cannot starve the store indefinitely;
//   * flush() writes anything outstanding right now, so the caller can drain
//     the queue on pagehide, on a hidden tab or before a session starts.
// No DOM, no storage and injectable timers, so all of it runs under node:test.

export const DEFAULT_WRITE_WINDOW_MS = 400;

export function createWriteCoalescer({
    write,
    windowMs = DEFAULT_WRITE_WINDOW_MS,
    setTimer = (fn, ms) => globalThis.setTimeout(fn, ms),
    clearTimer = (handle) => globalThis.clearTimeout(handle)
} = {}) {
    if (typeof write !== 'function') throw new TypeError('createWriteCoalescer needs a write function');
    const delay = Number.isFinite(windowMs) && windowMs > 0 ? windowMs : DEFAULT_WRITE_WINDOW_MS;
    let handle = null;
    let dirty = false;

    function disarm() {
        if (handle === null) return;
        try {
            clearTimer(handle);
        } catch (e) {
            // A timer that cannot be cleared must not strand the writer: the
            // callback re-checks `dirty` before it writes anything.
        }
        handle = null;
    }

    // Run the pending write, if any. `dirty` is cleared BEFORE the write so a
    // throwing or failing write cannot leave the coalescer looping on it; a
    // write that fails reports through its own return value, the way every
    // other storage write in the project does.
    function flush() {
        disarm();
        if (!dirty) return false;
        dirty = false;
        return write();
    }

    return {
        // Mark the settings changed. Returns true when this call armed the
        // window, false when it joined one that was already running.
        schedule() {
            dirty = true;
            if (handle !== null) return false;
            handle = setTimer(() => {
                handle = null;
                if (!dirty) return;
                dirty = false;
                write();
            }, delay);
            return true;
        },
        flush,
        // Drop a pending write without performing it. Only for a caller that
        // has just written the same data by another route.
        cancel() {
            disarm();
            const had = dirty;
            dirty = false;
            return had;
        },
        pending() {
            return dirty;
        },
        windowMs: delay
    };
}
