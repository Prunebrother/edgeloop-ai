/**
 * What the one alert banner is allowed to show.
 *
 * Every safety report in the app lands in the same `#disconnectBanner`:
 * heart-rate signal loss, a disconnected monitor, an offline Handy, a remote
 * link that died, and the worst of them, "the Handy did not confirm a stop
 * and may still be moving". Microphone advisories land there too. With no
 * rank, whichever fired LAST won and the earlier text was gone without trace,
 * so a microphone taken by another app a second later could erase the only
 * warning that a machine attached to the wearer might still be running.
 *
 * Two rules:
 *  - a lower-priority notice never overwrites a higher-priority one; it is
 *    appended, so neither message is lost;
 *  - a banner is only hidden again by whoever raised it, or by the wearer
 *    dismissing it by hand.
 *
 * Pure: no DOM. app.js holds the current banner state and does the writes.
 */

// Lowest to highest. An 'advisory' is worth telling the wearer about but says
// nothing about a motor; 'safety' reports something that can move, or has
// stopped reporting whether it is moving.
export const BANNER_SEVERITIES = ['none', 'advisory', 'safety'];

// The owner token that clears any banner: the wearer's own Dismiss button.
export const BANNER_OWNER_ANY = '*';

export function bannerRank(severity) {
    const i = BANNER_SEVERITIES.indexOf(severity);
    return i < 0 ? 0 : i;
}

// Keep both sentences rather than choosing between them. A repeat of the same
// text is not appended twice (the mic can fire `onmute` then `onended`).
export function mergeBannerMessage(currentText, incomingText) {
    const cur = typeof currentText === 'string' ? currentText.trim() : '';
    const inc = typeof incomingText === 'string' ? incomingText.trim() : '';
    if (!inc) return cur;
    if (!cur) return inc;
    if (cur.includes(inc)) return cur;
    return `${cur} Also: ${inc}`;
}

function normalizeCurrent(current) {
    const c = current && typeof current === 'object' ? current : {};
    return {
        visible: Boolean(c.visible),
        severity: BANNER_SEVERITIES.includes(c.severity) ? c.severity : 'none',
        source: typeof c.source === 'string' && c.source ? c.source : 'none',
        text: typeof c.text === 'string' ? c.text : ''
    };
}

// The banner state after `incoming` is reported over `current`.
export function planBannerUpdate(current, incoming = {}) {
    const cur = normalizeCurrent(current);
    const inc = incoming && typeof incoming === 'object' ? incoming : {};
    const severity = BANNER_SEVERITIES.includes(inc.severity) && inc.severity !== 'none'
        ? inc.severity
        : 'advisory';
    const source = typeof inc.source === 'string' && inc.source ? inc.source : 'device';
    const text = typeof inc.message === 'string' ? inc.message.trim() : '';
    if (!cur.visible || bannerRank(severity) >= bannerRank(cur.severity)) {
        return { visible: true, severity, source, text };
    }
    // Outranked: the standing report keeps the banner, its severity and its
    // owner, and the new sentence is added to it.
    return {
        visible: true,
        severity: cur.severity,
        source: cur.source,
        text: mergeBannerMessage(cur.text, text)
    };
}

// May `owner` hide what the banner is showing right now?
export function canClearBanner(current, owner) {
    if (owner === BANNER_OWNER_ANY) return true;
    const cur = normalizeCurrent(current);
    if (!cur.visible) return true;
    return cur.source === owner;
}

export function hiddenBannerState() {
    return { visible: false, severity: 'none', source: 'none', text: '' };
}
