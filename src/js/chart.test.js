import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { computeChartScale, shouldDrawPullbackLine, CHART_SAMPLES } from './chart.js';

describe('computeChartScale', () => {
    it('keeps the classic 50-180 window for ordinary limits', () => {
        assert.deepEqual(computeChartScale(70, 140), { lo: 50, hi: 180 });
    });

    it('extends the top so a Climax HR above 180 stays on the chart', () => {
        const scale = computeChartScale(70, 195);
        assert.ok(scale.hi >= 195 + 5, 'ceiling guide line must sit inside the scale');
        assert.equal(scale.lo, 50);
    });

    it('extends the top for an overshoot trigger above the typed climax', () => {
        const scale = computeChartScale(70, 140, 210);
        assert.ok(scale.hi >= 210 + 5);
    });

    it('extends the bottom for a very low resting HR', () => {
        const scale = computeChartScale(40, 140);
        assert.ok(scale.lo < 40);
        assert.equal(scale.hi, 180);
    });

    it('tolerates non-finite limits', () => {
        assert.deepEqual(computeChartScale(NaN, undefined), { lo: 50, hi: 180 });
    });

    it('keeps the 60-sample history window', () => {
        assert.equal(CHART_SAMPLES, 60);
    });
});

describe('shouldDrawPullbackLine', () => {
    it('draws the line whenever the pullback mark is not the ceiling', () => {
        // 95% of a 140 ceiling: the HOLD TO badge shows 133, so the chart
        // must show where that is.
        assert.equal(shouldDrawPullbackLine(133, 140), true);
        // A mark sent by a host that allows overshoot is still drawn.
        assert.equal(shouldDrawPullbackLine(147, 140), true);
    });

    it('draws nothing at 100%, where the mark IS the ceiling line', () => {
        assert.equal(shouldDrawPullbackLine(140, 140), false);
    });

    it('draws nothing without a usable mark', () => {
        // A remote page that has not been told the host's mark yet must not
        // invent one.
        assert.equal(shouldDrawPullbackLine(undefined, 140), false);
        assert.equal(shouldDrawPullbackLine(NaN, 140), false);
        assert.equal(shouldDrawPullbackLine(null, 140), false);
        assert.equal(shouldDrawPullbackLine(133, undefined), true);
    });
});
