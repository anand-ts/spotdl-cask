import { tblBody, tbl, ph, allBtn, removeAllBtn, cancelAllBtn } from './dom.js';
import { state, hasDownloadDirectory } from './state.js';
import { BUTTON_ICONS, DEFAULT_COVER_DATA_URI } from './constants.js';
import { fetchMetadata } from './api.js';
import {
    getStatusIcon,
    getStatusText,
    markActivity,
    setCoverImage,
    showToast
} from './ui.js';
import { handleRowSelection, removeSelectionForLink } from './selection.js';
import {
    updateCancelAllButtonState,
    updateDownloadAvailability,
    updateDownloadAllButtonState
} from './controls.js';

let rowActions = {
    dlOne: () => {},
    cancelOne: () => {},
    showInFinder: () => {}
};

export function setRowActionHandlers(actions) {
    rowActions = { ...rowActions, ...actions };
}

function createActionButton({ className, title, icon, hidden = false, onClick }) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.title = title;
    button.innerHTML = icon;
    if (hidden) {
        button.style.display = 'none';
    }
    button.addEventListener('click', event => {
        event.stopPropagation();
        onClick(event);
    });
    return button;
}

function cleanMetadataText(value) {
    if (value === null || value === undefined) {
        return '';
    }

    return String(value).trim();
}

function stringifyArtists(value) {
    if (Array.isArray(value)) {
        return value.map(cleanMetadataText).filter(Boolean).join(', ');
    }

    return cleanMetadataText(value);
}

function normalizeMetadata(metadata) {
    const payload = metadata && typeof metadata === 'object' ? metadata : {};

    return {
        cover: cleanMetadataText(payload.cover || payload.cover_url || payload.thumbnail || payload.image),
        title: cleanMetadataText(payload.title || payload.name || payload.track || payload.fulltitle) || '(unknown)',
        artist: cleanMetadataText(
            payload.artist ||
            stringifyArtists(payload.artists) ||
            payload.artist_name ||
            payload.author_name ||
            payload.album_artist ||
            payload.creator ||
            payload.uploader ||
            payload.channel
        ),
        album: cleanMetadataText(
            payload.album ||
            payload.album_name ||
            payload.album_title ||
            payload.playlist_title ||
            payload.playlist ||
            payload.collection
        )
    };
}

function createStatusElement(status) {
    const statusContainer = document.createElement('div');
    statusContainer.className = `status ${status}`;

    const statusIcon = document.createElement('span');
    statusIcon.className = `status-icon ${status}`;
    statusIcon.innerHTML = getStatusIcon(status);

    const statusText = document.createElement('span');
    statusText.className = 'status-text';
    statusText.textContent = getStatusText(status);

    statusContainer.appendChild(statusIcon);
    statusContainer.appendChild(statusText);
    return statusContainer;
}

function createRowElement(link, data) {
    const status = data.status || 'idle';
    const row = document.createElement('tr');
    row.dataset.link = link;
    row.dataset.status = status;
    row.dataset.canReveal = data.canReveal ? 'true' : 'false';
    row.setAttribute('aria-selected', 'false');
    row.tabIndex = -1;
    row.addEventListener('click', event => handleRowSelection(event, link));

    const coverCell = document.createElement('td');
    coverCell.className = 'cover-cell';
    const coverImg = document.createElement('img');
    coverImg.className = 'cover-image';
    coverImg.alt = 'Cover';
    coverImg.addEventListener('error', () => {
        coverImg.src = DEFAULT_COVER_DATA_URI;
    });
    setCoverImage(coverImg, data.cover);
    coverCell.appendChild(coverImg);

    const titleCell = document.createElement('td');
    titleCell.className = 'title-cell';
    titleCell.textContent = data.title || '';

    const artistCell = document.createElement('td');
    artistCell.className = 'artist-cell';
    artistCell.textContent = data.artist || '';

    const albumCell = document.createElement('td');
    albumCell.className = 'album-cell';
    albumCell.textContent = data.album || '';

    const statusCell = document.createElement('td');
    statusCell.className = 'status-cell';
    statusCell.appendChild(createStatusElement(status));

    const actionsCell = document.createElement('td');
    actionsCell.className = 'actions-cell';
    const actions = document.createElement('div');
    actions.className = 'actions';
    const isDownloading = status === 'downloading';

    actions.appendChild(createActionButton({
        className: 'dlbtn',
        title: 'Download',
        icon: BUTTON_ICONS.download,
        hidden: isDownloading,
        onClick: () => rowActions.dlOne(link)
    }));
    actions.appendChild(createActionButton({
        className: 'cancelbtn',
        title: 'Cancel Download',
        icon: BUTTON_ICONS.cancel,
        hidden: !isDownloading,
        onClick: () => rowActions.cancelOne(link)
    }));
    actions.appendChild(createActionButton({
        className: 'revealbtn',
        title: 'Show in Finder',
        icon: BUTTON_ICONS.reveal,
        hidden: status !== 'completed' || !data.canReveal,
        onClick: () => rowActions.showInFinder(link)
    }));
    actions.appendChild(createActionButton({
        className: 'xbtn',
        title: 'Remove',
        icon: BUTTON_ICONS.remove,
        onClick: () => rmRow(link)
    }));

    actionsCell.appendChild(actions);
    row.appendChild(coverCell);
    row.appendChild(titleCell);
    row.appendChild(artistCell);
    row.appendChild(albumCell);
    row.appendChild(statusCell);
    row.appendChild(actionsCell);

    if (status === 'loading') {
        row.classList.add('loading-row');
    }

    return row;
}

export function updateRowData(link, data) {
    const row = state.rows[link];
    if (!row) return;

    const coverImg = row.querySelector('.cover-image');
    const titleCell = row.querySelector('.title-cell');
    const artistCell = row.querySelector('.artist-cell');
    const albumCell = row.querySelector('.album-cell');
    const statusIcon = row.querySelector('.status-icon');
    const statusText = row.querySelector('.status-text');
    const dlBtn = row.querySelector('.dlbtn');
    const cancelBtn = row.querySelector('.cancelbtn');
    const revealBtn = row.querySelector('.revealbtn');
    const removeBtn = row.querySelector('.xbtn');

    if (data.canReveal !== undefined) {
        row.dataset.canReveal = data.canReveal ? 'true' : 'false';
    }
    const canReveal = row.dataset.canReveal === 'true';

    if (data.cover !== undefined) setCoverImage(coverImg, data.cover);
    if (data.title !== undefined) titleCell.textContent = data.title;
    if (data.artist !== undefined) artistCell.textContent = data.artist;
    if (data.album !== undefined) albumCell.textContent = data.album;

    if (data.status !== undefined) {
        statusIcon.className = `status-icon ${data.status}`;
        statusIcon.innerHTML = getStatusIcon(data.status);
        statusText.textContent = getStatusText(data.status);
        row.dataset.status = data.status;

        const statusContainer = row.querySelector('.status');
        if (statusContainer) {
            statusContainer.className = `status ${data.status}`;
        }

        if (data.status === 'downloading') {
            if (dlBtn) { dlBtn.style.display = 'none'; dlBtn.disabled = true; }
            if (cancelBtn) { cancelBtn.style.display = 'flex'; cancelBtn.disabled = false; }
            if (revealBtn) { revealBtn.style.display = 'none'; revealBtn.disabled = true; }
            if (removeBtn) { removeBtn.disabled = true; }
        } else if (data.status === 'completed') {
            if (dlBtn) { dlBtn.style.display = 'none'; dlBtn.disabled = true; }
            if (cancelBtn) { cancelBtn.style.display = 'none'; cancelBtn.disabled = true; }
            if (revealBtn) {
                revealBtn.style.display = canReveal ? 'flex' : 'none';
                revealBtn.disabled = !canReveal;
            }
            if (removeBtn) { removeBtn.disabled = false; }
        } else {
            if (dlBtn) { dlBtn.style.display = 'flex'; dlBtn.disabled = !hasDownloadDirectory(); }
            if (cancelBtn) { cancelBtn.style.display = 'none'; cancelBtn.disabled = true; }
            if (revealBtn) { revealBtn.style.display = 'none'; revealBtn.disabled = true; }
            if (removeBtn) { removeBtn.disabled = false; }
        }

        row.classList.remove('loading-row');
    }
}

export function updateStatus(link, status, extraData = {}) {
    if (!state.rows[link]) return;

    updateRowData(link, { status, ...extraData });

    const statusCell = state.rows[link].querySelector('.status-cell');
    if (statusCell) {
        const existingProgress = statusCell.querySelector('.progress-wrapper');
        if (status !== 'downloading' && existingProgress) {
            existingProgress.remove();
        }
    }
}

export function rmRow(link) {
    if (!state.rows[link]) return;
    markActivity();
    removeSelectionForLink(link);

    const row = state.rows[link];
    const trackTitle = row.querySelector('.title-cell').textContent;

    row.style.transition = 'all 0.25s ease';
    row.style.opacity = '0';
    row.style.transform = 'translateX(-20px)';

    setTimeout(() => {
        if (row.parentElement) {
            tblBody.removeChild(row);
        }

        delete state.rows[link];
        delete state.lastStatusCache[link];
        delete state.lastErrorCache[link];

        if (!Object.keys(state.rows).length) {
            ph.style.display = 'block';
            tbl.style.display = 'none';
            allBtn.disabled = true;
            cancelAllBtn.disabled = true;
            removeAllBtn.disabled = true;
        }

        updateDownloadAvailability();
        updateDownloadAllButtonState();
        updateCancelAllButtonState();
        showToast(`Removed: ${trackTitle}`, 'info', 2000);
    }, 250);
}

export function addRow(link) {
    markActivity();
    if (state.rows[link]) {
        showToast('Link already added', 'info', 2000);
        return;
    }

    delete state.lastStatusCache[link];
    delete state.lastErrorCache[link];

    const row = createRowElement(link, {
        cover: '',
        title: 'Loading...',
        artist: 'Loading...',
        album: 'Loading...',
        status: 'loading'
    });

    tblBody.appendChild(row);
    state.rows[link] = row;
    ph.style.display = 'none';
    tbl.style.display = 'table';
    allBtn.disabled = false;
    removeAllBtn.disabled = false;
    updateDownloadAvailability();
    updateCancelAllButtonState();

    requestAnimationFrame(() => {
        row.style.opacity = '0';
        row.style.transform = 'translateY(10px)';
        row.style.transition = 'all 0.3s ease';

        requestAnimationFrame(() => {
            row.style.opacity = '1';
            row.style.transform = 'translateY(0)';
        });
    });

    fetchMetadata(link)
        .then(metadata => {
            if (!state.rows[link]) return;
            const normalizedMetadata = normalizeMetadata(metadata);
            updateRowData(link, {
                cover: normalizedMetadata.cover,
                title: normalizedMetadata.title,
                artist: normalizedMetadata.artist,
                album: normalizedMetadata.album,
                status: 'idle'
            });
            showToast(`Added: ${normalizedMetadata.title || 'Unknown track'}`, 'success', 3000);
        })
        .catch(error => {
            console.error('Error fetching metadata:', error);
            if (!state.rows[link]) return;

            updateRowData(link, {
                cover: '',
                title: 'Metadata unavailable',
                artist: '',
                album: '',
                status: 'error'
            });

            showToast(error.message || 'Failed to load track metadata', 'error', 6000);
        });
}
