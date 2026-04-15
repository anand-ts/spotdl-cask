export const state = {
    rows: {},
    selectedLinks: new Set(),
    selectionAnchorLink: null,
    settings: {
        downloadDirectory: '',
        quality: 'best',
        format: 'mp3',
        output: '{artists} - {title}.{output-ext}',
        playlistNumbering: false,
        skipExplicit: false,
        generateLrc: false
    },
    settingsLoaded: false,
    lastStatusCache: {},
    lastErrorCache: {},
    lastActivityTs: Date.now(),
    headerIdle: true
};

export function normalizeDownloadDirectory(value) {
    return typeof value === 'string' ? value.trim() : '';
}

export function hasDownloadDirectory() {
    return normalizeDownloadDirectory(state.settings.downloadDirectory).length > 0;
}
