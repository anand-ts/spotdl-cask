// Simplified JavaScript for new UI

// DOM Elements
const tblBody = document.querySelector('#tbl-body');
const ph = document.getElementById('ph');
const allBtn = document.getElementById('allBtn');
const cancelAllBtn = document.getElementById('cancelAllBtn');
const removeAllBtn = document.getElementById('removeAllBtn');
const sidebar = document.getElementById('sidebar');
const overlay = document.getElementById('overlay');
const zone = document.getElementById('zone');
const headerTitle = document.getElementById('headerTitle');

// Header idle animation state mgmt
let lastActivityTs = Date.now();
let headerIdle = true;
const IDLE_ANIMATION_DELAY_MS = 5000; // configurable idle timeout

function setHeaderIdle(idle) {
    if (!headerTitle) return;
    if (idle) {
        if (!headerTitle.classList.contains('idle')) headerTitle.classList.add('idle');
        headerIdle = true;
    } else {
        if (headerTitle.classList.contains('idle')) headerTitle.classList.remove('idle');
        headerIdle = false;
    }
}

// Mark any user / download activity
function markActivity() {
    lastActivityTs = Date.now();
    if (headerIdle) setHeaderIdle(false);
}

// Poll for idleness (no downloads and no activity for 5s)
setInterval(() => {
    const anyDownloading = Object.keys(rows).some(link => {
        const row = rows[link];
        return row && row.querySelector('.status-text')?.textContent.trim() === 'Downloading...';
    });
    if (anyDownloading) {
        markActivity(); // keep active while downloading
    }
    if (!anyDownloading && (Date.now() - lastActivityTs) > IDLE_ANIMATION_DELAY_MS) {
        setHeaderIdle(true);
    }
}, 1500);

// Application State
let rows = {};
let settings = {
    quality: 'best',
    format: 'mp3',
    output: '{artists} - {title}.{output-ext}',
    playlistNumbering: false,
    skipExplicit: false,
    generateLrc: false
};

// Cache of last applied statuses to minimize DOM thrash
const lastStatusCache = {};

// Event Listeners
document.addEventListener('paste', e => {
    markActivity();
    const txt = (e.clipboardData || window.clipboardData).getData('text');
    const links = txt.split(/[\s,]+/).filter(t => t.startsWith('http'));
    if (!links.length) {
        showToast('No valid links found in clipboard', 'info', 2000);
        return;
    }
    e.preventDefault();
    
    showToast(`Processing ${links.length} link${links.length > 1 ? 's' : ''}...`, 'info', 2000);
    links.forEach(addRow);
});

// Row Management
function addRow(link) {
    markActivity();
    if (rows[link]) {
        showToast('Link already added', 'info', 2000);
        return;
    }
    
    // Create row with loading state using template
    const row = createRowElement(link, {
        cover: '',
        title: 'Loading...',
        artist: 'Loading...',
        album: 'Loading...',
        status: 'loading'
    });
    
    // Add to DOM and state
    tblBody.appendChild(row);
    rows[link] = row;
    
    // Show table and enable controls
    ph.style.display = 'none';
    document.getElementById('tbl').style.display = 'table';
    allBtn.disabled = false;
    removeAllBtn.disabled = false;
    
    // Add entrance animation
    requestAnimationFrame(() => {
        row.style.opacity = '0';
        row.style.transform = 'translateY(10px)';
        row.style.transition = 'all 0.3s ease';
        
        requestAnimationFrame(() => {
            row.style.opacity = '1';
            row.style.transform = 'translateY(0)';
        });
    });
    
    // Fetch metadata and update row
    fetch('/meta', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link })
    })
    .then(response => response.json())
    .then(metadata => {
        if (!rows[link]) return; // Row was removed during fetch
        
        updateRowData(link, {
            cover: metadata.cover || '',
            title: metadata.title || '(unknown)',
            artist: metadata.artist || '',
            album: metadata.album || '',
            status: 'idle'
        });
        
        showToast(`Added: ${metadata.title || 'Unknown track'}`, 'success', 3000);
    })
    .catch(error => {
        console.error('Error fetching metadata:', error);
        if (!rows[link]) return;
        
        updateRowData(link, {
            cover: '',
            title: 'Error loading metadata',
            artist: 'Error',
            album: 'Error',
            status: 'error'
        });
        
        showToast('Failed to load track metadata', 'error', 3000);
    });
}

// Create a table row element with given data
function createRowElement(link, data) {
    const row = document.createElement('tr');
    row.dataset.link = link;
    row.dataset.status = data.status || 'idle';
    row.innerHTML = `
        <td class="cover-cell">
            <img src="${data.cover || 'data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'128\' height=\'128\' viewBox=\'0 0 128 128\'%3E%3Crect fill=\'%23333\' width=\'128\' height=\'128\'/%3E%3Cpath fill=\'%23666\' d=\'M64 40c-13.254 0-24 10.746-24 24s10.746 24 24 24 24-10.746 24-24-10.746-24-24-24zm0 40c-8.822 0-16-7.178-16-16s7.178-16 16-16 16 7.178 16 16-7.178 16-16 16z\'/%3E%3Ccircle fill=\'%23666\' cx=\'64\' cy=\'64\' r=\'6\'/%3E%3C/svg%3E'}" alt="Cover" onerror="this.src='data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'128\' height=\'128\' viewBox=\'0 0 128 128\'%3E%3Crect fill=\'%23333\' width=\'128\' height=\'128\'/%3E%3Cpath fill=\'%23666\' d=\'M64 40c-13.254 0-24 10.746-24 24s10.746 24 24 24 24-10.746 24-24-10.746-24-24-24zm0 40c-8.822 0-16-7.178-16-16s7.178-16 16-16 16 7.178 16 16-7.178 16-16 16z\'/%3E%3Ccircle fill=\'%23666\' cx=\'64\' cy=\'64\' r=\'6\'/%3E%3C/svg%3E'">
        </td>
        <td class="title-cell">${data.title}</td>
        <td class="artist-cell">${data.artist}</td>
        <td class="album-cell">${data.album}</td>
        <td class="status-cell">
            <div class="status ${data.status}">
                <span class="status-icon ${data.status}">
                    ${getStatusIcon(data.status)}
                </span>
                <span class="status-text">${getStatusText(data.status)}</span>
            </div>
        </td>
        <td class="actions-cell">
            <div class="actions">
                <button class="dlbtn" onclick="dlOne('${link}')" title="Download" ${data.status === 'downloading' ? 'style="display:none"' : ''}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="7,10 12,15 17,10"></polyline>
                        <line x1="12" y1="15" x2="12" y2="3"></line>
                    </svg>
                </button>
                <button class="cancelbtn" onclick="cancelOne('${link}')" title="Cancel Download" ${data.status !== 'downloading' ? 'style="display:none"' : ''}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="12" cy="12" r="10"></circle>
                        <line x1="15" y1="9" x2="9" y2="15"></line>
                        <line x1="9" y1="9" x2="15" y2="15"></line>
                    </svg>
                </button>
                <button class="xbtn" onclick="rmRow('${link}')" title="Remove">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            </div>
        </td>
    `;
    
    if (data.status === 'loading') {
        row.classList.add('loading-row');
    }
    
    return row;
}

// Update row data without recreating the entire row
function updateRowData(link, data) {
    const row = rows[link];
    if (!row) return;
    
    const coverImg = row.querySelector('.cover-cell img');
    const titleCell = row.querySelector('.title-cell');
    const artistCell = row.querySelector('.artist-cell');
    const albumCell = row.querySelector('.album-cell');
    const statusIcon = row.querySelector('.status-icon');
    const statusText = row.querySelector('.status-text');
    
    if (data.cover !== undefined) {
        if (data.cover) {
            coverImg.src = data.cover;
            coverImg.style.opacity = '1';
        } else {
            coverImg.src = 'data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'128\' height=\'128\' viewBox=\'0 0 128 128\'%3E%3Crect fill=\'%23333\' width=\'128\' height=\'128\'/%3E%3Cpath fill=\'%23666\' d=\'M64 40c-13.254 0-24 10.746-24 24s10.746 24 24 24 24-10.746 24-24-10.746-24-24-24zm0 40c-8.822 0-16-7.178-16-16s7.178-16 16-16 16 7.178 16 16-7.178 16-16 16z\'/%3E%3Ccircle fill=\'%23666\' cx=\'64\' cy=\'64\' r=\'6\'/%3E%3C/svg%3E';
            coverImg.style.opacity = '1';
        }
    }
    
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
        
        const dlBtn = row.querySelector('.dlbtn');
        const cancelBtn = row.querySelector('.cancelbtn');
        const removeBtn = row.querySelector('.xbtn');
        
        if (data.status === 'downloading') {
            if (dlBtn) { dlBtn.style.display = 'none'; dlBtn.disabled = true; }
            if (cancelBtn) { cancelBtn.style.display = 'flex'; cancelBtn.disabled = false; }
            if (removeBtn) { removeBtn.disabled = true; }
        } else {
            if (dlBtn) { dlBtn.style.display = 'flex'; dlBtn.disabled = (data.status === 'completed'); }
            if (cancelBtn) { cancelBtn.style.display = 'none'; cancelBtn.disabled = true; }
            if (removeBtn) { removeBtn.disabled = false; }
        }
        
        row.classList.remove('loading-row');
    }
}

// Get status icon SVG
function getStatusIcon(status) {
    const icons = {
        loading: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="loading-spinner"><path d="M21 12a9 9 0 11-6.219-8.56"></path></svg>`,
        idle: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1"></circle></svg>`,
        downloading: ``, // No icon, just progress bar
        completed: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6 9 17l-5-5"></path></svg>`,
        error: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`
    };
    return icons[status] || icons.idle;
}

// Get status text
function getStatusText(status) {
    const texts = {
        loading: 'Loading...',
        idle: 'Ready',
        downloading: 'Downloading...',
        completed: 'Downloaded',
        error: 'Error'
    };
    return texts[status] || 'Unknown';
}

function rmRow(l) {
    if (!rows[l]) return;
    markActivity();
    
    const row = rows[l];
    const trackTitle = row.querySelector('.title-cell').textContent;
    
    row.style.transition = 'all 0.25s ease';
    row.style.opacity = '0';
    row.style.transform = 'translateX(-20px)';
    
    setTimeout(() => {
        if (row.parentElement) {
            tblBody.removeChild(row);
        }
        delete rows[l];
        
        if (!Object.keys(rows).length) {
            ph.style.display = 'block';
            document.getElementById('tbl').style.display = 'none';
            allBtn.disabled = true;
            cancelAllBtn.disabled = true;
            removeAllBtn.disabled = true;
        }
        
        showToast(`Removed: ${trackTitle}`, 'info', 2000);
    }, 250);
}

// Download Management
function dlOne(link) {
    if (!rows[link]) return;
    markActivity();
    
    const dlBtn = rows[link].querySelector('.dlbtn');
    const statusCell = rows[link].querySelector('.status-cell');
    
    dlBtn.disabled = true;
    updateStatus(link, 'downloading');
    
    updateCancelAllButtonState();
    
    const progressBar = addProgressBar(statusCell, 0);
    
    fetch('/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link, ...settings })
    })
    .catch(error => {
        console.error('Download start failed:', error);
        updateStatus(link, 'error');
        dlBtn.disabled = false;
        showToast('Download failed', 'error', 4000);
    });
}

function cancelOne(link) {
    if (!rows[link]) return;
    markActivity();
    
    const cancelBtn = rows[link].querySelector('.cancelbtn');
    const trackTitle = rows[link].querySelector('.title-cell').textContent;
    
    if (cancelBtn) cancelBtn.disabled = true;
    
    fetch('/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link })
    })
    .then(response => {
        if (response.ok) {
            updateStatus(link, 'idle');
            updateDownloadAllButtonState();
            showToast(`Cancelled: ${trackTitle}`, 'info', 3000);
        } else {
            showToast('Failed to cancel download', 'error', 3000);
            if (cancelBtn) cancelBtn.disabled = false;
        }
    })
    .catch(error => {
        console.error('Cancel request failed:', error);
        showToast('Failed to cancel download', 'error', 3000);
        if (cancelBtn) cancelBtn.disabled = false;
    });
}

allBtn.addEventListener('click', () => {
    markActivity();
    const allLinks = Object.keys(rows);
    if (allLinks.length === 0) return;
    
    const pendingLinks = allLinks.filter(link => {
        const row = rows[link];
        const st = row?.dataset.status;
        return st !== 'downloading' && st !== 'completed' && st !== 'loading' && st !== 'error';
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
    const allLinks = Object.keys(rows);
    if (!allLinks.length) return;

    const linksToCancel = allLinks.filter(link => {
        const row = rows[link];
        if (!row) return false;
        const statusText = row.querySelector('.status-text')?.textContent.trim() || '';
        return statusText === 'Downloading...';
    });

    if (!linksToCancel.length) {
        showToast('No active downloads to cancel', 'info', 2000);
        return;
    }

    showToast(`Cancelling ${linksToCancel.length} download${linksToCancel.length > 1 ? 's' : ''}...`, 'info', 2000);
    linksToCancel.forEach(link => cancelOne(link));
});

removeAllBtn.addEventListener('click', () => {
    markActivity();
    const linkCount = Object.keys(rows).length;
    if (linkCount === 0) return;
    
    showToast(`Removing all ${linkCount} track${linkCount > 1 ? 's' : ''}...`, 'info', 2000);
    Object.keys(rows).forEach(link => rmRow(link));
});

// Settings Management
function toggleSettings() {
    sidebar.classList.add('open');
    overlay.classList.add('show');
}

function closeSettings() {
    sidebar.classList.remove('open');
    overlay.classList.remove('show');
}

function applySettings() {
    const qualityRadio = document.querySelector('input[name="quality"]:checked');
    settings.quality = qualityRadio ? qualityRadio.value : 'best';
    settings.format = document.getElementById('formatSel').value;
    settings.output = document.getElementById('outputSel').value;
    settings.playlistNumbering = document.getElementById('playlistNumbering').checked;
    settings.skipExplicit = document.getElementById('skipExplicit').checked;
    settings.generateLrc = document.getElementById('generateLrc').checked;
    
    closeSettings();
    showToast('Settings saved successfully!', 'success', 3000);
    console.log('Applied settings:', settings);
}

// Status Update
function updateStatus(link, status) {
    if (!rows[link]) return;
    
    updateRowData(link, { status: status });
    
    const statusCell = rows[link].querySelector('.status-cell');
    if (statusCell) {
        const existingProgress = statusCell.querySelector('.progress-wrapper');
        if (status !== 'downloading' && existingProgress) {
            existingProgress.remove();
        }
    }
}

// Status Polling
setInterval(() => {
    const qs = Object.keys(rows);
    if (!qs.length) return;
    
    fetch('/status?links=' + encodeURIComponent(qs.join(',')))
        .then(r => r.json())
        .then(statuses => {
            let totalProgress = 0;
            let activeCount = 0;
            qs.forEach(link => {
                const data = statuses[link];
                if (!data || !rows[link]) return;
                
                const newStatusName = data.status === 'done' ? 'completed' : data.status;
                if (lastStatusCache[link] !== newStatusName) {
                    updateStatus(link, newStatusName);
                    lastStatusCache[link] = newStatusName;
                }

                if (data.status === 'downloading') {
                    let progressBar = rows[link].querySelector('.progress-bar');
                    if (!progressBar) {
                        const statusCell = rows[link].querySelector('.status-cell');
                        progressBar = addProgressBar(statusCell, data.progress);
                    }
                    updateProgressBar(progressBar, data.progress);
                    totalProgress += (data.progress <= 1 ? data.progress * 100 : data.progress);
                    activeCount += 1;
                }
            });
            
            updateDownloadAllButtonState();
            // Update aggregate progress if button is in downloading state
            if (activeCount > 0 && allBtn.innerHTML.includes('Downloading')) {
                const aggPct = Math.round(totalProgress / activeCount);
                const span = allBtn.querySelector('.agg-progress');
                if (span) span.textContent = `${aggPct}%`;
            }
        });
}, 1000);

// UI Feedback
function showToast(message, type = 'info', duration = 4000) {
    const toastContainer = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    const icons = {
        success: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22,4 12,14.01 9,11.01"></polyline></svg>`,
        error: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line></svg>`,
        info: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`
    };
    
    toast.innerHTML = `
        <div class="toast-icon" style="color: ${type === 'success' ? 'var(--green)' : type === 'error' ? '#f44336' : '#2196F3'}">${icons[type]}</div>
        <div class="toast-message">${message}</div>
        <button class="toast-close" onclick="this.parentElement.remove()"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg></button>
    `;
    
    toastContainer.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, duration);
}

function addProgressBar(element, progress = 0) {
    if (!element) return null;
    const existing = element.querySelector('.progress-wrapper');
    if (existing) return existing.querySelector('.progress-bar');
    const statusBlock = element.querySelector('.status');
    const wrapper = document.createElement('div');
    wrapper.className = 'progress-wrapper';
    const bar = document.createElement('div');
    bar.className = 'progress-bar';
    // Support fractional (0..1) or percentage (0..100)
    const pct = progress <= 1 ? progress * 100 : progress;
    bar.style.width = `${pct}%`;
    const text = document.createElement('div');
    text.className = 'progress-text';
    text.textContent = `${Math.round(pct)}%`;
    wrapper.appendChild(bar);
    wrapper.appendChild(text);
    // Append after status block to keep icon/text visible
    if (statusBlock) {
        statusBlock.after(wrapper);
    } else {
        element.appendChild(wrapper);
    }
    return bar;
}

function updateProgressBar(bar, progress) {
    if (!bar) return;
    const pctRaw = progress <= 1 ? progress * 100 : progress;
    const clampedProgress = Math.min(100, Math.max(0, pctRaw));
    bar.style.width = `${clampedProgress}%`;
    const wrapper = bar.parentElement;
    const text = wrapper ? wrapper.querySelector('.progress-text') : null;
    if (text) text.textContent = `${Math.round(clampedProgress)}%`;
}

// Drag and Drop
function setupDragAndDrop() {
    const dropZone = document.getElementById('ph');
    
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, e => { e.preventDefault(); e.stopPropagation(); }, false);
        document.body.addEventListener(eventName, e => { e.preventDefault(); e.stopPropagation(); }, false);
    });
    
    ['dragenter', 'dragover'].forEach(eventName => dropZone.addEventListener(eventName, () => dropZone.classList.add('drag-over'), false));
    ['dragleave', 'drop'].forEach(eventName => dropZone.addEventListener(eventName, () => dropZone.classList.remove('drag-over'), false));
    
    dropZone.addEventListener('drop', e => {
        const text = e.dataTransfer.getData('text');
        if (text) {
            const links = text.split(/[\s,]+/).filter(t => t.startsWith('http'));
            if (links.length > 0) {
                showToast(`Processing ${links.length} link${links.length > 1 ? 's' : ''}...`, 'info');
                links.forEach(addRow);
            }
        }
    }, false);
}

// Button State Management
function updateDownloadAllButtonState() {
    const allLinks = Object.keys(rows);
    if (allLinks.length === 0) {
        resetDownloadAllButton();
        updateCancelAllButtonState();
        return;
    }
    const isAnyDownloading = allLinks.some(link => rows[link].dataset.status === 'downloading');
    if (!isAnyDownloading) {
        resetDownloadAllButton();
    }
    updateCancelAllButtonState();
}

function resetDownloadAllButton() {
    allBtn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7,10 12,15 17,10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg> Download All`;
    allBtn.disabled = (Object.keys(rows).length === 0);
    removeAllBtn.disabled = (Object.keys(rows).length === 0);
}

function updateCancelAllButtonState() {
    const allLinks = Object.keys(rows);
    if (allLinks.length === 0) {
        cancelAllBtn.disabled = true;
        return;
    }
    const isAnyDownloading = allLinks.some(link => rows[link].dataset.status === 'downloading');
    cancelAllBtn.disabled = !isAnyDownloading;
}

// Dark Mode
function toggleDarkMode() {
    const body = document.body;
    const isDarkMode = body.getAttribute('data-theme') === 'dark';
    const newTheme = isDarkMode ? 'light' : 'dark';
    body.setAttribute('data-theme', newTheme);
    updateDarkModeIcon(newTheme);
    localStorage.setItem('darkMode', newTheme);
    showToast(`Switched to ${newTheme} mode`, 'info', 2000);
}

function updateDarkModeIcon(theme) {
    const icon = document.getElementById('darkModeIcon');
    if (!icon) return;
    if (theme === 'dark') {
        icon.innerHTML = `<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>`;
    } else {
        icon.innerHTML = `<circle cx="12" cy="12" r="5"></circle><path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72 1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"></path>`;
    }
}

function initializeDarkMode() {
    const savedTheme = localStorage.getItem('darkMode');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = savedTheme || (prefersDark ? 'dark' : 'light');
    document.body.setAttribute('data-theme', theme);
    updateDarkModeIcon(theme);
}

// DOM ready
document.addEventListener('DOMContentLoaded', () => {
    initializeDarkMode();
    setupDragAndDrop();
    updateDownloadAllButtonState();
    updateCancelAllButtonState();
    // Start in idle visual state
    setHeaderIdle(true);
});

// Utility functions
function resetUI() {
    // Reset the UI elements to their initial state
    document.getElementById('progress-container').style.display = 'none';
    document.getElementById('download-link').style.display = 'none';
    document.getElementById('status-message').textContent = '';
}

function showElement(id) {
    document.getElementById(id).style.display = 'block';
}

function hideElement(id) {
    document.getElementById(id).style.display = 'none';
}

function showSongInfo(metadata) {
    // Display the fetched song metadata
    document.getElementById('song-title').textContent = metadata.title || 'Unknown Title';
    document.getElementById('song-artist').textContent = metadata.artist || 'Unknown Artist';
    document.getElementById('song-album').textContent = metadata.album || 'Unknown Album';
    document.getElementById('cover-image').src = metadata.cover || 'default-cover.jpg';
    document.getElementById('cover-image').style.display = 'block';
}

function updateProgress(progress) {
    const progressBar = document.getElementById('progress-bar');
    progressBar.style.width = `${progress}%`;
    progressBar.setAttribute('aria-valuenow', progress);
    document.getElementById('progress-text').textContent = `${progress}%`;
}

function showDownloadLink(filepath) {
    const downloadLink = document.getElementById('download-link');
    downloadLink.href = filepath;
    downloadLink.style.display = 'block';
    downloadLink.textContent = 'Download your file';
}