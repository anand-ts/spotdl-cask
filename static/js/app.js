// DOM Elements
const tblBody = document.querySelector('#tbl tbody');
const ph = document.getElementById('ph');
const allBtn = document.getElementById('allBtn');
const cancelAllBtn = document.getElementById('cancelAllBtn');
const removeAllBtn = document.getElementById('removeAllBtn');
const sidebar = document.getElementById('sidebar');
const overlay = document.getElementById('overlay');
const zone = document.getElementById('zone');

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

// Event Listeners
document.addEventListener('paste', e => {
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
    // Cancel All button will be enabled/disabled based on download status
    
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
    row.innerHTML = `
        <td class="cover-cell">
            <img src="${data.cover}" alt="Cover" style="opacity: ${data.cover ? 1 : 0}">
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
        </td>
    `;
    
    // Add loading skeleton if needed
    if (data.status === 'loading') {
        row.classList.add('loading-row');
    }
    
    return row;
}

// Update row data without recreating the entire row
function updateRowData(link, data) {
    const row = rows[link];
    if (!row) return;
    
    // Update cells using class selectors (more robust than indexes)
    const coverImg = row.querySelector('.cover-cell img');
    const titleCell = row.querySelector('.title-cell');
    const artistCell = row.querySelector('.artist-cell');
    const albumCell = row.querySelector('.album-cell');
    const statusIcon = row.querySelector('.status-icon');
    const statusText = row.querySelector('.status-text');
    
    if (data.cover !== undefined) {
        coverImg.src = data.cover;
        coverImg.style.opacity = data.cover ? '1' : '0';
    }
    
    if (data.title !== undefined) titleCell.textContent = data.title;
    if (data.artist !== undefined) artistCell.textContent = data.artist;
    if (data.album !== undefined) albumCell.textContent = data.album;
    
    if (data.status !== undefined) {
        statusIcon.className = `status-icon ${data.status}`;
        statusIcon.innerHTML = getStatusIcon(data.status);
        statusText.textContent = getStatusText(data.status);
        
        // Update status container class for special downloading layout
        const statusContainer = row.querySelector('.status');
        if (statusContainer) {
            statusContainer.className = `status ${data.status}`;
        }
        
        // Update button visibility and state based on status
        const dlBtn = row.querySelector('.dlbtn');
        const cancelBtn = row.querySelector('.cancelbtn');
        
        if (data.status === 'downloading') {
            if (dlBtn) {
                dlBtn.style.display = 'none';
                dlBtn.disabled = true;
            }
            if (cancelBtn) {
                cancelBtn.style.display = 'flex';
                cancelBtn.disabled = false;
            }
        } else {
            if (dlBtn) {
                dlBtn.style.display = 'flex';
                dlBtn.disabled = false; // Re-enable for any non-downloading status
            }
            if (cancelBtn) {
                cancelBtn.style.display = 'none';
                cancelBtn.disabled = false;
            }
        }
        
        // Remove loading class if present
        row.classList.remove('loading-row');
    }
}

// Get status icon SVG
function getStatusIcon(status) {
    const icons = {
        loading: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M21 12a9 9 0 11-6.219-8.56"></path>
                  </svg>`,
        idle: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="3"></circle>
                <circle cx="12" cy="2" r="1"></circle>
                <circle cx="12" cy="22" r="1"></circle>
                <circle cx="2" cy="12" r="1"></circle>
                <circle cx="22" cy="12" r="1"></circle>
              </svg>`,
        downloading: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                       <path d="M12 2v6m0 4v10"></path>
                       <path d="m8 18 4 4 4-4"></path>
                       <circle cx="12" cy="8" r="2"></circle>
                     </svg>`,
        completed: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                     <circle cx="12" cy="12" r="10"></circle>
                     <path d="m9 12 2 2 4-4"></path>
                   </svg>`,
        error: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                 <circle cx="12" cy="12" r="10"></circle>
                 <path d="M12 8v4"></path>
                 <path d="m12 16 .01 0"></path>
               </svg>`
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
    
    const row = rows[l];
    const trackTitle = row.querySelector('.title-cell').textContent;
    
    // Get the current height before animating
    const rowHeight = row.offsetHeight;
    
    // Phase 1: Fade out and slide
    row.style.transition = 'all 0.25s ease';
    row.style.opacity = '0';
    row.style.transform = 'translateX(-20px) scale(0.95)';
    
    setTimeout(() => {
        // Phase 2: Collapse height
        row.style.transition = 'all 0.2s ease';
        row.style.height = '0px';
        row.style.padding = '0';
        row.style.margin = '0';
        row.style.overflow = 'hidden';
        
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
        }, 200);
    }, 250);
}

// Download Management
function dlOne(link) {
    if (!rows[link]) return;
    
    const dlBtn = rows[link].querySelector('.dlbtn');
    const statusCell = rows[link].querySelector('.status-cell');
    
    dlBtn.disabled = true;
    updateStatus(link, 'downloading', 'Downloading...');
    
    // Update Cancel All button state
    updateCancelAllButtonState();
    
    // Add progress bar
    const progressBar = addProgressBar(statusCell, 0);
    
    // Start the download
    fetch('/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link, ...settings })
    })
    .then(response => {
        if (response.ok) {
            // Start listening for real-time progress updates via Server-Sent Events
            startProgressStream(link, progressBar, dlBtn);
        } else {
            updateStatus(link, 'error', 'Error');
            dlBtn.disabled = false;
            showToast('Download failed', 'error', 4000);
        }
    })
    .catch(error => {
        console.error('Download start failed:', error);
        updateStatus(link, 'error', 'Failed');
        dlBtn.disabled = false;
        showToast('Download failed', 'error', 4000);
    });
}

function startProgressStream(link, progressBar, dlBtn) {
    if (!rows[link]) return;
    
    // Create EventSource for Server-Sent Events
    const encodedLink = encodeURIComponent(link);
    const eventSource = new EventSource(`/progress/${encodedLink}`);
    
    eventSource.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            
            if (data.link === link && rows[link]) {
                // Update progress bar
                updateProgressBar(progressBar, data.progress);
                
                // Check if download is complete
                if (data.complete) {
                    eventSource.close();
                    
                    if (data.status === 'error') {
                        updateStatus(link, 'error', 'Error');
                        dlBtn.disabled = false;
                        showToast('Download failed', 'error', 4000);
                    } else {
                        updateStatus(link, 'completed', 'Downloaded');
                        const trackTitle = rows[link].querySelector('.title-cell').textContent;
                        showToast(`Downloaded: ${trackTitle}`, 'success', 4000);
                    }
                    
                    // Update Download All button state
                    updateDownloadAllButtonState();
                }
            }
        } catch (error) {
            console.error('Error parsing progress data:', error);
        }
    };
    
    eventSource.onerror = function(event) {
        console.error('Progress stream error:', event);
        eventSource.close();
        
        // Fallback: check status via polling
        setTimeout(() => {
            if (rows[link]) {
                checkDownloadStatus(link, dlBtn);
            }
        }, 1000);
    };
    
    // Clean up on page unload
    window.addEventListener('beforeunload', () => {
        eventSource.close();
    });
}

function checkDownloadStatus(link, dlBtn) {
    // Fallback status check if SSE fails
    fetch(`/status?links=${encodeURIComponent(link)}`)
        .then(response => response.json())
        .then(status => {
            const linkStatus = status[link];
            if (linkStatus === 'done') {
                updateStatus(link, 'completed', 'Downloaded');
                const trackTitle = rows[link].querySelector('.title-cell').textContent;
                showToast(`Downloaded: ${trackTitle}`, 'success', 4000);
                updateDownloadAllButtonState();
            } else if (linkStatus === 'error') {
                updateStatus(link, 'error', 'Error');
                dlBtn.disabled = false;
                showToast('Download failed', 'error', 4000);
                updateDownloadAllButtonState();
            } else if (linkStatus === 'downloading') {
                // Still downloading, check again
                setTimeout(() => checkDownloadStatus(link, dlBtn), 2000);
            }
        })
        .catch(error => {
            console.error('Status check failed:', error);
            updateStatus(link, 'error', 'Failed');
            dlBtn.disabled = false;
            updateDownloadAllButtonState();
        });
}

function cancelOne(link) {
    if (!rows[link]) return;
    
    const cancelBtn = rows[link].querySelector('.cancelbtn');
    const trackTitle = rows[link].querySelector('.title-cell').textContent;
    
    if (cancelBtn) cancelBtn.disabled = true;
    
    // Send cancel request
    fetch('/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link })
    })
    .then(response => {
        if (response.ok) {
            updateStatus(link, 'idle', 'Ready');
            
            // Re-enable the download button
            const dlBtn = rows[link].querySelector('.dlbtn');
            if (dlBtn) dlBtn.disabled = false;
            
            // Check if we should update the Download All button state
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

function dlAll() {
    const allLinks = Object.keys(rows);
    if (allLinks.length === 0) return;
    
    // Filter out songs that are already downloading or completed
    const pendingLinks = allLinks.filter(link => {
        const row = rows[link];
        const statusCell = row.querySelector('.status-cell');
        const statusText = statusCell.querySelector('.status-text');
        const currentStatus = statusText ? statusText.textContent.trim() : '';
        
        // Skip if already downloading or completed
        return currentStatus !== 'Downloading...' && currentStatus !== 'Downloaded';
    });
    
    if (pendingLinks.length === 0) {
        showToast('All tracks are already downloaded or downloading', 'info', 3000);
        return;
    }
    
    const linkCount = pendingLinks.length;
    showToast(`Starting download of ${linkCount} track${linkCount > 1 ? 's' : ''}...`, 'info', 3000);
    
    // Only download pending tracks
    pendingLinks.forEach(dlOne);
    
    allBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="loading-spinner">
            <path d="M21 12a9 9 0 11-6.219-8.56"></path>
        </svg>
        Downloading…
    `;
    allBtn.disabled = true;
    removeAllBtn.disabled = true;
    // Cancel All button will be enabled automatically when downloads start
}

function cancelAll() {
    const allLinks = Object.keys(rows);
    if (allLinks.length === 0) return;
    
    // Filter out songs that are currently downloading
    const downloadingLinks = allLinks.filter(link => {
        const row = rows[link];
        const statusCell = row.querySelector('.status-cell');
        const statusText = statusCell.querySelector('.status-text');
        const currentStatus = statusText ? statusText.textContent.trim() : '';
        
        // Only cancel if currently downloading
        return currentStatus === 'Downloading...';
    });
    
    if (downloadingLinks.length === 0) {
        showToast('No downloads to cancel', 'info', 2000);
        return;
    }
    
    const linkCount = downloadingLinks.length;
    showToast(`Cancelling ${linkCount} download${linkCount > 1 ? 's' : ''}...`, 'info', 2000);
    
    // Cancel all downloading tracks
    downloadingLinks.forEach(cancelOne);
}

function removeAllTracks() {
    const linkCount = Object.keys(rows).length;
    if (linkCount === 0) return;
    
    showToast(`Removing all ${linkCount} track${linkCount > 1 ? 's' : ''}...`, 'info', 2000);
    
    // Remove all rows with animation
    Object.keys(rows).forEach(link => rmRow(link));
}

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

// Status Icon Management
function updateStatus(link, status, text) {
    if (!rows[link]) return;
    
    // Use the new updateRowData function for consistency
    updateRowData(link, { 
        status: status 
    });
    
    // Handle progress bars for downloading status
    const statusCell = rows[link].querySelector('.status-cell');
    if (status === 'downloading') {
        // Clear any existing progress bars first
        const existingProgress = statusCell.querySelector('.progress-wrapper');
        if (existingProgress) {
            existingProgress.remove();
        }
    } else {
        // Clear progress bars for non-downloading states
        const existingProgress = statusCell.querySelector('.progress-wrapper');
        if (existingProgress) {
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
        .then(st => {
            qs.forEach(l => {
                const s = st[l];
                if (!s || !rows[l]) return;
                
                if (s === 'done') {
                    updateStatus(l, 'completed', 'Downloaded');
                } else if (s === 'error') {
                    updateStatus(l, 'error', 'error');
                    rows[l].querySelector('.dlbtn').disabled = false;
                }
            });
            
            // Update Download All button state based on current status
            updateDownloadAllButtonState();
        });
}, 2000);

// Visual Feedback Functions
function showToast(message, type = 'info', duration = 4000) {
    const toastContainer = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    
    const icons = {
        success: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                    <polyline points="22,4 12,14.01 9,11.01"></polyline>
                  </svg>`,
        error: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                 <circle cx="12" cy="12" r="10"></circle>
                 <line x1="15" y1="9" x2="9" y2="15"></line>
                 <line x1="9" y1="9" x2="15" y2="15"></line>
               </svg>`,
        info: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="16" x2="12" y2="12"></line>
                <line x1="12" y1="8" x2="12.01" y2="8"></line>
              </svg>`
    };
    
    toast.innerHTML = `
        <div class="toast-icon" style="color: ${type === 'success' ? 'var(--green)' : type === 'error' ? '#f44336' : '#2196F3'}">
            ${icons[type]}
        </div>
        <div class="toast-message">${message}</div>
        <button class="toast-close" onclick="hideToast(this.parentElement)">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
        </button>
    `;
    
    toastContainer.appendChild(toast);
    
    // Trigger animation
    setTimeout(() => toast.classList.add('show'), 10);
    
    // Auto-hide
    setTimeout(() => hideToast(toast), duration);
    
    return toast;
}

function hideToast(toast) {
    toast.classList.remove('show');
    setTimeout(() => {
        if (toast.parentElement) {
            toast.parentElement.removeChild(toast);
        }
    }, 300);
}

function showLoadingOverlay() {
    document.getElementById('loadingOverlay').classList.add('show');
}

function hideLoadingOverlay() {
    document.getElementById('loadingOverlay').classList.remove('show');
}



function addProgressBar(element, progress = 0) {
    const wrapper = document.createElement('div');
    wrapper.className = 'progress-wrapper';
    
    const bar = document.createElement('div');
    bar.className = 'progress-bar';
    bar.style.width = `${progress}%`;
    
    wrapper.appendChild(bar);
    element.appendChild(wrapper);
    
    return bar;
}

function updateProgressBar(bar, progress) {
    const clampedProgress = Math.min(100, Math.max(0, progress));
    bar.style.width = `${clampedProgress}%`;
    
    // Update progress text if it exists
    const progressWrapper = bar.parentElement;
    let progressText = progressWrapper.querySelector('.progress-text');
    
    if (!progressText) {
        progressText = document.createElement('div');
        progressText.className = 'progress-text';
        progressWrapper.appendChild(progressText);
    }
    
    progressText.textContent = `${Math.round(clampedProgress)}%`;
}

// Enhanced Drag and Drop
function setupDragAndDrop() {
    const dropZone = document.getElementById('ph');
    
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, preventDefaults, false);
        document.body.addEventListener(eventName, preventDefaults, false);
    });
    
    ['dragenter', 'dragover'].forEach(eventName => {
        dropZone.addEventListener(eventName, highlight, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, unhighlight, false);
    });
    
    dropZone.addEventListener('drop', handleDrop, false);
    
    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
    function highlight(e) {
        dropZone.classList.add('drag-over');
    }
    
    function unhighlight(e) {
        dropZone.classList.remove('drag-over');
    }
    
    function handleDrop(e) {
        const dt = e.dataTransfer;
        const text = dt.getData('text');
        
        if (text) {
            const links = text.split(/[\s,]+/).filter(t => t.startsWith('http'));
            if (links.length > 0) {
                showToast(`Processing ${links.length} link${links.length > 1 ? 's' : ''}...`, 'info');
                links.forEach(addRow);
            }
        }
    }
}

// Debug and utility functions
function clearAllRows() {
    rows = {};
    tblBody.innerHTML = '';
    ph.style.display = 'block';
    document.getElementById('tbl').style.display = 'none';
    allBtn.disabled = true;
    removeAllBtn.disabled = true;
    showToast('Cleared all tracks', 'info', 2000);
}

// Add to window for debugging
window.clearAllRows = clearAllRows;

// Download All Button State Management
function updateDownloadAllButtonState() {
    const allLinks = Object.keys(rows);
    if (allLinks.length === 0) {
        resetDownloadAllButton();
        updateCancelAllButtonState();
        return;
    }
    
    // Check if any tracks are currently downloading
    const isAnyDownloading = allLinks.some(link => {
        const row = rows[link];
        const statusCell = row.querySelector('.status-cell');
        const statusText = statusCell.querySelector('.status-text');
        const currentStatus = statusText ? statusText.textContent.trim() : '';
        return currentStatus === 'Downloading...';
    });
    
    if (!isAnyDownloading) {
        resetDownloadAllButton();
    }
    
    // Always update Cancel All button state
    updateCancelAllButtonState();
}

function resetDownloadAllButton() {
    allBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
            <polyline points="7,10 12,15 17,10"></polyline>
            <line x1="12" y1="15" x2="12" y2="3"></line>
        </svg>
        Download All
    `;
    allBtn.disabled = false;
    removeAllBtn.disabled = false;
}

function updateCancelAllButtonState() {
    const allLinks = Object.keys(rows);
    if (allLinks.length === 0) {
        cancelAllBtn.disabled = true;
        return;
    }
    
    // Check if any tracks are currently downloading
    const isAnyDownloading = allLinks.some(link => {
        const row = rows[link];
        const statusCell = row.querySelector('.status-cell');
        const statusText = statusCell.querySelector('.status-text');
        const currentStatus = statusText ? statusText.textContent.trim() : '';
        return currentStatus === 'Downloading...';
    });
    
    cancelAllBtn.disabled = !isAnyDownloading;
}

// Dark Mode Functionality
function toggleDarkMode() {
    const body = document.body;
    const isDarkMode = body.getAttribute('data-theme') === 'dark';
    const newTheme = isDarkMode ? 'light' : 'dark';
    
    body.setAttribute('data-theme', newTheme);
    
    // Update the toggle button icon
    updateDarkModeIcon(newTheme);
    
    // Save preference to localStorage
    localStorage.setItem('darkMode', newTheme);
    
    // Show toast notification
    showToast(`Switched to ${newTheme} mode`, 'info', 2000);
}

function updateDarkModeIcon(theme) {
    const icon = document.getElementById('darkModeIcon');
    if (!icon) return;
    
    if (theme === 'dark') {
        // Moon icon for dark mode
        icon.innerHTML = `
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
        `;
    } else {
        // Sun icon for light mode
        icon.innerHTML = `
            <circle cx="12" cy="12" r="5"></circle>
            <path d="M12 1v2"></path>
            <path d="M12 21v2"></path>
            <path d="M4.22 4.22l1.42 1.42"></path>
            <path d="M18.36 18.36l1.42 1.42"></path>
            <path d="M1 12h2"></path>
            <path d="M21 12h2"></path>
            <path d="M4.22 19.78l1.42-1.42"></path>
            <path d="M18.36 5.64l1.42-1.42"></path>
        `;
    }
}

// Initialize dark mode on page load
function initializeDarkMode() {
    const savedTheme = localStorage.getItem('darkMode');
    const prefersDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
    
    // Use saved preference, or fall back to system preference
    const theme = savedTheme || (prefersDarkMode ? 'dark' : 'light');
    
    document.body.setAttribute('data-theme', theme);
    updateDarkModeIcon(theme);
}

// Initialize dark mode when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    initializeDarkMode();
    setupDragAndDrop();
});
