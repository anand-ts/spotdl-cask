import { allBtn, cancelAllBtn, removeAllBtn } from './dom.js';
import { state, hasDownloadDirectory } from './state.js';

export function updateDownloadAvailability() {
    const configured = hasDownloadDirectory();

    Object.values(state.rows).forEach(row => {
        if (!row) return;
        const dlBtn = row.querySelector('.dlbtn');
        if (!dlBtn) return;

        const status = row.dataset.status;
        if (status === 'downloading') return;

        dlBtn.disabled = !configured || status === 'completed';
    });

    if (!allBtn.innerHTML.includes('Downloading')) {
        allBtn.disabled = Object.keys(state.rows).length === 0 || !configured;
    }
}

export function resetDownloadAllButton() {
    allBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7,10 12,15 17,10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg> Download All`;
    allBtn.disabled = Object.keys(state.rows).length === 0 || !hasDownloadDirectory();
    removeAllBtn.disabled = Object.keys(state.rows).length === 0;
}

export function updateCancelAllButtonState() {
    const allLinks = Object.keys(state.rows);
    if (allLinks.length === 0) {
        cancelAllBtn.disabled = true;
        return;
    }

    const isAnyDownloading = allLinks.some(link => state.rows[link].dataset.status === 'downloading');
    cancelAllBtn.disabled = !isAnyDownloading;
}

export function updateDownloadAllButtonState() {
    const allLinks = Object.keys(state.rows);
    if (allLinks.length === 0) {
        resetDownloadAllButton();
        updateCancelAllButtonState();
        return;
    }

    const isAnyDownloading = allLinks.some(link => state.rows[link].dataset.status === 'downloading');
    if (!isAnyDownloading) {
        resetDownloadAllButton();
    }

    updateCancelAllButtonState();
}
