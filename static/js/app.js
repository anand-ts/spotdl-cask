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
        <td class='status'>idle</td>
        <td class='actions'>
            <button class='dlbtn' onclick="dlOne('${link}')">Download</button>
            <button class='xbtn' onclick="rmRow('${link}')">✕</button>
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
    
    rows[link].querySelector('.dlbtn').disabled = true;
    rows[link].querySelector('.status').innerHTML = '<progress></progress>';
    
    fetch('/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link, ...settings })
    });
}

function dlAll() {
    Object.keys(rows).forEach(dlOne);
    allBtn.textContent = 'Downloading…';
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
                    rows[l].querySelector('.status').textContent = '✓';
                } else if (s === 'error') {
                    rows[l].querySelector('.status').textContent = 'error';
                    rows[l].querySelector('.dlbtn').disabled = false;
                }
            });
            
            if (Object.values(st).every(v => v === 'done' || v === 'error')) {
                allBtn.textContent = 'Download All';
                allBtn.disabled = false;
            }
        });
}, 2000);
