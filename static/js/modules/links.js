export function normalizeInputLink(rawLink) {
    const trimmed = String(rawLink || '').trim().replace(/[)\].,;]+$/g, '');
    if (!/^https?:\/\//i.test(trimmed)) return '';

    try {
        const url = new URL(trimmed);
        url.hash = '';

        if (url.hostname.toLowerCase() === 'open.spotify.com') {
            const parts = url.pathname.split('/').filter(Boolean);
            const trackIndex = parts.findIndex(part => part.toLowerCase() === 'track');
            const trackId = parts[trackIndex + 1];
            if (trackIndex >= 0 && trackId) {
                return `${url.protocol}//${url.hostname}/track/${trackId}`;
            }
        }

        return url.toString();
    } catch (_error) {
        return trimmed;
    }
}

export function extractLinksFromText(text) {
    const links = [];
    const seen = new Set();
    const tokens = String(text || '').split(/[\s,]+/);

    tokens.forEach(token => {
        const link = normalizeInputLink(token);
        if (!link || seen.has(link)) return;

        seen.add(link);
        links.push(link);
    });

    return links;
}
