/**
 * Renders the 60-second sliding telemetry graph.
 *
 * The canvas bitmap follows its CSS box and the device pixel ratio (never a
 * fixed 800x110), so the curve is crisp on phones and the width matches the
 * layout. The y-scale always contains both guide lines, so a Climax HR
 * above 180 BPM is drawn instead of vanishing off the top.
 */
export const CHART_SAMPLES = 60;
const BASE_MIN = 50;
const BASE_MAX = 180;
const MARGIN = 10;

// Pure: the BPM range the y-axis covers for the given guide lines.
export function computeChartScale(minHr, maxHr, triggerHr) {
    let lo = BASE_MIN;
    let hi = BASE_MAX;
    if (Number.isFinite(minHr)) lo = Math.min(lo, minHr - MARGIN);
    if (Number.isFinite(maxHr)) hi = Math.max(hi, maxHr + MARGIN);
    if (Number.isFinite(triggerHr)) hi = Math.max(hi, triggerHr + MARGIN);
    lo = Math.max(0, Math.floor(lo));
    hi = Math.ceil(hi);
    if (hi - lo < 20) hi = lo + 20;
    return { lo, hi };
}

// Pure: whether the purple pullback line has anything to say. At 100% the
// mark IS the ceiling, which is already drawn in red; anywhere else (a 90-99%
// pullback, or an overshoot mark sent by a remote host) the wearer is shown
// where the crawl / Full Stop rule really starts. A missing or unusable mark
// draws nothing: a remote page that has not heard the host's number yet must
// never fabricate one.
export function shouldDrawPullbackLine(triggerHr, maxHr) {
    if (!Number.isFinite(triggerHr)) return false;
    return !Number.isFinite(maxHr) || triggerHr !== maxHr;
}

// Size the bitmap from the CSS box. Returns null when the canvas has no
// layout yet (hidden), in which case nothing should be drawn.
function fitCanvas(canvas) {
    const rect = canvas.getBoundingClientRect();
    const cssWidth = rect.width || canvas.clientWidth;
    const cssHeight = rect.height || canvas.clientHeight;
    if (!cssWidth || !cssHeight) return null;
    const dpr = (typeof window !== 'undefined' && window.devicePixelRatio) || 1;
    const width = Math.max(1, Math.round(cssWidth * dpr));
    const height = Math.max(1, Math.round(cssHeight * dpr));
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    return { width: cssWidth, height: cssHeight, dpr };
}

// Redraw whenever the canvas box changes (orientation, window resize).
// Returns a function that stops watching.
export function watchChartResize(canvas, redraw) {
    if (!canvas || typeof redraw !== 'function') return () => {};
    if (typeof ResizeObserver === 'function') {
        const observer = new ResizeObserver(() => redraw());
        observer.observe(canvas);
        return () => observer.disconnect();
    }
    if (typeof window !== 'undefined') {
        window.addEventListener('resize', redraw);
        return () => window.removeEventListener('resize', redraw);
    }
    return () => {};
}

export function drawTelemetryChart(canvas, history, minHr, maxHr, triggerHr) {
    if (!canvas) return;
    const box = fitCanvas(canvas);
    if (!box) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const { width, height, dpr } = box;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const { lo, hi } = computeChartScale(minHr, maxHr, triggerHr);
    const scaleY = (val) => height - ((val - lo) / (hi - lo)) * height;

    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);

    // Resting HR floor guide line
    if (Number.isFinite(minHr)) {
        ctx.strokeStyle = '#14b8a6';
        ctx.beginPath();
        ctx.moveTo(0, scaleY(minHr));
        ctx.lineTo(width, scaleY(minHr));
        ctx.stroke();
    }

    // Climax HR ceiling guide line
    if (Number.isFinite(maxHr)) {
        ctx.strokeStyle = '#f43f5e';
        ctx.beginPath();
        ctx.moveTo(0, scaleY(maxHr));
        ctx.lineTo(width, scaleY(maxHr));
        ctx.stroke();
    }

    // Pullback mark (the HOLD TO badge's number)
    if (shouldDrawPullbackLine(triggerHr, maxHr)) {
        ctx.strokeStyle = '#c084fc';
        ctx.beginPath();
        ctx.moveTo(0, scaleY(triggerHr));
        ctx.lineTo(width, scaleY(triggerHr));
        ctx.stroke();
    }

    ctx.setLineDash([]);

    // Telemetry curve: the newest CHART_SAMPLES readings, right-aligned.
    const samples = Array.isArray(history) ? history.slice(-CHART_SAMPLES) : [];
    if (samples.length < 2) return;
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#f43f5e';
    ctx.beginPath();
    const step = width / (CHART_SAMPLES - 1);
    const offset = CHART_SAMPLES - samples.length;
    samples.forEach((val, i) => {
        const x = (offset + i) * step;
        const y = scaleY(Number.isFinite(val) ? val : lo);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();
}
