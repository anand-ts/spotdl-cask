// DOM Elements
const tblBody = document.querySelector('#tbl tbody');
const ph = document.getElementById('ph');
const allBtn = document.getElementById('allBtn');
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
    if (!links.length) return;
    e.preventDefault();
    links.forEach(addRow);
});

// Row Management
function addRow(link) {
    if (rows[link]) return;
    
    const r = document.createElement('tr');
    r.innerHTML = `
        <td><img/></td>
        <td>-</td>
        <td>-</td>
        <td>-</td>
        <td class='status'>
            <span class='status-icon idle'>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"></circle>
                    <path d="M8 12h8"></path>
                </svg>
            </span>
            <span class='status-text'>idle</span>
        </td>
        <td class='actions'>
            <button class='dlbtn' onclick="dlOne('${link}')" title='Download'>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="7,10 12,15 17,10"></polyline>
                    <line x1="12" y1="15" x2="12" y2="3"></line>
                </svg>
            </button>
            <button class='xbtn' onclick="rmRow('${link}')" title='Remove'>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
            </button>
        </td>
    `;
    
    tblBody.appendChild(r);
    rows[link] = r;
    ph.style.display = 'none';
    document.getElementById('tbl').style.display = 'table';
    allBtn.disabled = false;
    
    // Fetch metadata
    fetch('/meta', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link })
    })
    .then(r => r.json())
    .then(m => {
        if (!rows[link]) return;
        r.children[0].firstChild.src = m.cover || '';
        r.children[1].textContent = m.title || '(unknown)';
        r.children[2].textContent = m.artist || '';
        r.children[3].textContent = m.album || '';
    })
    .catch(() => {});
}

function rmRow(l) {
    if (!rows[l]) return;
    tblBody.removeChild(rows[l]);
    delete rows[l];
    
    if (!Object.keys(rows).length) {
        ph.style.display = 'block';
        document.getElementById('tbl').style.display = 'none';
        allBtn.disabled = true;
    }
}

// Download Management
function dlOne(link) {
    if (!rows[link]) return;
    
    const dlBtn = rows[link].querySelector('.dlbtn');
    dlBtn.disabled = true;
    updateStatus(link, 'downloading', 'Downloading...');
    
    fetch('/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link, ...settings })
    })
    .then(response => {
        if (response.ok) {
            updateStatus(link, 'completed', 'Downloaded');
        } else {
            updateStatus(link, 'error', 'Error');
            dlBtn.disabled = false;
        }
    })
    .catch(() => {
        updateStatus(link, 'error', 'Failed');
        dlBtn.disabled = false;
    });
}

function dlAll() {
    Object.keys(rows).forEach(dlOne);
    allBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="loading-spinner">
            <path d="M21 12a9 9 0 11-6.219-8.56"></path>
        </svg>
        Downloading…
    `;
    allBtn.disabled = true;
}

// Settings Management
function toggleSettings() {
    sidebar.classList.add('open');
    overlay.classList.add('show');
    zone.classList.add('zone-shifted');
}

function closeSettings() {
    sidebar.classList.remove('open');
    overlay.classList.remove('show');
    zone.classList.remove('zone-shifted');
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
    console.log('Applied settings:', settings);
}

// Status Icon Management
function updateStatus(link, status, text) {
    if (!rows[link]) return;
    
    const statusCell = rows[link].querySelector('.status');
    const statusIcons = {
        idle: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"></circle>
                <path d="M8 12h8"></path>
              </svg>`,
        downloading: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                       <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                       <polyline points="7,10 12,15 17,10"></polyline>
                       <line x1="12" y1="15" x2="12" y2="3"></line>
                     </svg>`,
        completed: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                     <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                     <polyline points="22,4 12,14.01 9,11.01"></polyline>
                   </svg>`,
        error: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                 <circle cx="12" cy="12" r="10"></circle>
                 <line x1="15" y1="9" x2="9" y2="15"></line>
                 <line x1="9" y1="9" x2="15" y2="15"></line>
               </svg>`,
        progress: `<div class="progress-container">
                     <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="loading-spinner">
                       <path d="M21 12a9 9 0 11-6.219-8.56"></path>
                     </svg>
                   </div>`
    };
    
    if (status === 'progress') {
        statusCell.innerHTML = `
            <span class='status-icon ${status}'>
                ${statusIcons[status]}
            </span>
            <progress></progress>
        `;
    } else {
        statusCell.innerHTML = `
            <span class='status-icon ${status}'>
                ${statusIcons[status]}
            </span>
            <span class='status-text'>${text || status}</span>
        `;
    }
    
    // Remove old status classes and add new one
    statusCell.className = `status ${status}`;
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
                    updateStatus(l, 'completed', '✓');
                } else if (s === 'error') {
                    updateStatus(l, 'error', 'error');
                    rows[l].querySelector('.dlbtn').disabled = false;
                }
            });
            
            if (Object.values(st).every(v => v === 'done' || v === 'error')) {
                allBtn.textContent = 'Download All';
                allBtn.disabled = false;
            }
        });
}, 2000);
