import { allBtn, cancelAllBtn, removeAllBtn } from './dom.js';
import {
    cancelDownloadRequest,
    fetchStatuses,
    revealDownloadRequest,
    startDownloadRequest
} from './api.js';
import { state, hasDownloadDirectory } from './state.js';
import {
    addProgressBar,
    markActivity,
    normalizeProgress,
    showToast,
    updateProgressBar
} from './ui.js';
import {
    updateCancelAllButtonState,
    updateDownloadAllButtonState
} from './controls.js';
import { ensureDownloadDirectoryConfigured } from './settings.js';
import { addRow, rmRow, updateStatus } from './rows.js';
import { removeSelectionForLink } from './selection.js';

export function dlOne(link) {
    if (!state.rows[link]) return;
    if (!ensureDownloadDirectoryConfigured()) return;
    markActivity();

    const dlBtn = state.rows[link].querySelector('.dlbtn');
    const statusCell = state.rows[link].querySelector('.status-cell');

    delete state.lastErrorCache[link];
    dlBtn.disabled = true;
    updateStatus(link, 'downloading');
    updateCancelAllButtonState();
    addProgressBar(statusCell, 0);

    startDownloadRequest(link, state.settings)
        .catch(error => {
            console.error('Download start failed:', error);
            updateStatus(link, 'error');
            dlBtn.disabled = !hasDownloadDirectory();
            updateDownloadAllButtonState();
            showToast(error.message || 'Download failed', 'error', 4000);
        });
}

export function cancelOne(link) {
    if (!state.rows[link]) return;
    markActivity();

    const cancelBtn = state.rows[link].querySelector('.cancelbtn');
    const trackTitle = state.rows[link].querySelector('.title-cell').textContent;

    if (cancelBtn) cancelBtn.disabled = true;

    cancelDownloadRequest(link)
        .then(() => {
            updateStatus(link, 'idle');
            updateDownloadAllButtonState();
            showToast(`Cancelled: ${trackTitle}`, 'info', 3000);
        })
        .catch(error => {
            console.error('Cancel request failed:', error);
            showToast('Failed to cancel download', 'error', 3000);
            if (cancelBtn) cancelBtn.disabled = false;
        });
}

export function showInFinder(link) {
    if (!state.rows[link]) return;
    markActivity();

    revealDownloadRequest(link)
        .then(() => {
            showToast('Revealed in Finder', 'info', 2200);
        })
        .catch(error => {
            console.error('Reveal request failed:', error);
            showToast(error.message || 'Could not reveal the downloaded file.', 'error', 4000);
        });
}

export function startStatusPolling() {
    setInterval(() => {
        const links = Object.keys(state.rows).filter(link => state.rows[link]?.dataset.status === 'downloading');
        if (!links.length) return;

        fetchStatuses(links).then(statuses => {
            let totalProgress = 0;
            let activeCount = 0;

            links.forEach(link => {
                const data = statuses[link];
                if (!data || !state.rows[link]) return;

                const newStatusName = data.status === 'done' ? 'completed' : data.status;
                const canReveal = Boolean(data.can_reveal);
                const revealStateChanged = state.rows[link].dataset.canReveal !== String(canReveal);
                if (state.lastStatusCache[link] !== newStatusName || revealStateChanged) {
                    updateStatus(link, newStatusName, { canReveal });
                    state.lastStatusCache[link] = newStatusName;
                }

                if (newStatusName === 'error' && data.error_message && state.lastErrorCache[link] !== data.error_message) {
                    state.lastErrorCache[link] = data.error_message;
                    showToast(data.error_message, 'error', 7000);
                }

                if (data.status === 'downloading') {
                    let progressBar = state.rows[link].querySelector('.progress-bar');
                    if (!progressBar) {
                        const statusCell = state.rows[link].querySelector('.status-cell');
                        progressBar = addProgressBar(statusCell, data.progress);
                    }
                    updateProgressBar(progressBar, data.progress);
                    totalProgress += normalizeProgress(data.progress);
                    activeCount += 1;
                }
            });

            updateDownloadAllButtonState();
            if (activeCount > 0 && allBtn.innerHTML.includes('Downloading')) {
                const aggPct = Math.round(totalProgress / activeCount);
                const span = allBtn.querySelector('.agg-progress');
                if (span) span.textContent = `${aggPct}%`;
            }
        });
    }, 1000);
}

export function installDownloadControls() {
    allBtn.addEventListener('click', () => {
        if (!ensureDownloadDirectoryConfigured()) return;
        markActivity();
        const allLinks = Object.keys(state.rows);
        if (allLinks.length === 0) return;

        const pendingLinks = allLinks.filter(link => {
            const row = state.rows[link];
            const status = row?.dataset.status;
            return status !== 'downloading' && status !== 'completed' && status !== 'loading';
        });

        if (pendingLinks.length === 0) {
            showToast('All tracks are already downloaded or downloading', 'info', 3000);
            return;
        }

        const linkCount = pendingLinks.length;
        showToast(`Starting download of ${linkCount} track${linkCount > 1 ? 's' : ''}...`, 'info', 3000);
        pendingLinks.forEach(dlOne);

        allBtn.innerHTML = `<span class="agg-progress">0%</span> <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="loading-spinner"><path d="M21 12a9 9 0 11-6.219-8.56"></path></svg> Downloading…`;
        allBtn.disabled = true;
        removeAllBtn.disabled = true;
        cancelAllBtn.disabled = false;
    });

    cancelAllBtn.addEventListener('click', () => {
        markActivity();
        const allLinks = Object.keys(state.rows);
        if (!allLinks.length) return;

        const linksToCancel = allLinks.filter(link => {
            const row = state.rows[link];
            if (!row) return false;
            const statusText = row.querySelector('.status-text')?.textContent.trim() || '';
            return statusText === 'Downloading...';
        });

        if (!linksToCancel.length) {
            showToast('No active downloads to cancel', 'info', 2000);
            return;
        }

        showToast(`Cancelling ${linksToCancel.length} download${linksToCancel.length > 1 ? 's' : ''}...`, 'info', 2000);
        linksToCancel.forEach(cancelOne);
    });

    removeAllBtn.addEventListener('click', () => {
        markActivity();
        const linkCount = Object.keys(state.rows).length;
        if (linkCount === 0) return;

        showToast(`Removing all ${linkCount} track${linkCount > 1 ? 's' : ''}...`, 'info', 2000);
        Object.keys(state.rows).forEach(link => {
            removeSelectionForLink(link);
            rmRow(link);
        });
    });
}

export function installPasteHandler() {
    document.addEventListener('paste', event => {
        markActivity();
        const text = (event.clipboardData || window.clipboardData).getData('text');
        const links = text.split(/[\s,]+/).filter(token => token.startsWith('http'));
        if (!links.length) {
            showToast('No valid links found in clipboard', 'info', 2000);
            return;
        }

        event.preventDefault();
        showToast(`Processing ${links.length} link${links.length > 1 ? 's' : ''}...`, 'info', 2000);
        links.forEach(addRow);
    });
}
