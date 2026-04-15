import { compactToggleBtn, headerTitle, toastContainer } from './dom.js';
import { state } from './state.js';
import {
    CLOSE_ICON_SVG,
    COMPACT_MODE_STORAGE_KEY,
    DEFAULT_COVER_DATA_URI,
    IDLE_ANIMATION_DELAY_MS,
    TOAST_ICONS
} from './constants.js';

export function setHeaderIdle(idle) {
    if (!headerTitle) return;
    if (idle) {
        if (!headerTitle.classList.contains('idle')) headerTitle.classList.add('idle');
        state.headerIdle = true;
        return;
    }

    if (headerTitle.classList.contains('idle')) headerTitle.classList.remove('idle');
    state.headerIdle = false;
}

export function markActivity() {
    state.lastActivityTs = Date.now();
    if (state.headerIdle) {
        setHeaderIdle(false);
    }
}

export function startIdleMonitor() {
    setInterval(() => {
        const anyDownloading = Object.keys(state.rows).some(link => {
            const row = state.rows[link];
            return row && row.querySelector('.status-text')?.textContent.trim() === 'Downloading...';
        });

        if (anyDownloading) {
            markActivity();
        }

        if (!anyDownloading && (Date.now() - state.lastActivityTs) > IDLE_ANIMATION_DELAY_MS) {
            setHeaderIdle(true);
        }
    }, 1500);
}

export function getCoverSrc(cover) {
    return cover || DEFAULT_COVER_DATA_URI;
}

export function setCoverImage(img, cover) {
    img.src = getCoverSrc(cover);
    img.style.opacity = '1';
}

export function getStatusIcon(status) {
    const icons = {
        loading: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="loading-spinner"><path d="M21 12a9 9 0 11-6.219-8.56"></path></svg>`,
        idle: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="1"></circle></svg>`,
        downloading: ``,
        completed: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6 9 17l-5-5"></path></svg>`,
        error: `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`
    };
    return icons[status] || icons.idle;
}

export function getStatusText(status) {
    const texts = {
        loading: 'Loading...',
        idle: 'Ready',
        downloading: 'Downloading...',
        completed: 'Downloaded',
        error: 'Error'
    };
    return texts[status] || 'Unknown';
}

export function showToast(message, type = 'info', duration = 4000) {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icon = document.createElement('div');
    icon.className = 'toast-icon';
    icon.style.color = type === 'success' ? 'var(--green)' : type === 'error' ? '#f44336' : '#2196F3';
    icon.innerHTML = TOAST_ICONS[type] || TOAST_ICONS.info;

    const messageNode = document.createElement('div');
    messageNode.className = 'toast-message';
    messageNode.textContent = String(message);

    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'toast-close';
    closeButton.innerHTML = CLOSE_ICON_SVG;
    closeButton.addEventListener('click', () => toast.remove());

    toast.appendChild(icon);
    toast.appendChild(messageNode);
    toast.appendChild(closeButton);
    toastContainer.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

export function normalizeProgress(p) {
    if (p == null || isNaN(p)) return 0;
    if (p >= 2) return Math.min(100, p);
    if (p === 0) return 0;
    return 1;
}

export function addProgressBar(element, progress = 0) {
    if (!element) return null;
    const existing = element.querySelector('.progress-wrapper');
    if (existing) return existing.querySelector('.progress-bar');
    const statusBlock = element.querySelector('.status');
    const wrapper = document.createElement('div');
    wrapper.className = 'progress-wrapper';
    const bar = document.createElement('div');
    bar.className = 'progress-bar';
    const pct = normalizeProgress(progress);
    bar.style.width = `${pct}%`;
    const text = document.createElement('div');
    text.className = 'progress-text';
    text.textContent = `${Math.round(pct)}%`;
    wrapper.appendChild(bar);
    wrapper.appendChild(text);
    if (statusBlock) {
        statusBlock.after(wrapper);
    } else {
        element.appendChild(wrapper);
    }
    return bar;
}

export function updateProgressBar(bar, progress) {
    if (!bar) return;
    const pct = normalizeProgress(progress);
    bar.style.width = `${pct}%`;
    const wrapper = bar.parentElement;
    const text = wrapper ? wrapper.querySelector('.progress-text') : null;
    if (text) text.textContent = `${Math.round(pct)}%`;
}

export function updateCompactToggleState(compact) {
    if (!compactToggleBtn) return;
    compactToggleBtn.classList.toggle('active', compact);
    compactToggleBtn.setAttribute('aria-pressed', compact ? 'true' : 'false');
    compactToggleBtn.title = compact
        ? 'Switch to standard list view'
        : 'Switch to compact list view';
}

export function setCompactMode(compact, notify = false) {
    document.body.classList.toggle('compact-mode', compact);
    localStorage.setItem(COMPACT_MODE_STORAGE_KEY, compact ? 'compact' : 'standard');
    updateCompactToggleState(compact);
    if (notify) {
        showToast(compact ? 'Compact view enabled' : 'Standard view restored', 'info', 2000);
    }
}

export function toggleCompactMode() {
    markActivity();
    const compact = !document.body.classList.contains('compact-mode');
    setCompactMode(compact, true);
}

export function initializeCompactMode() {
    const savedMode = localStorage.getItem(COMPACT_MODE_STORAGE_KEY);
    setCompactMode(savedMode === 'compact');
}

export function toggleDarkMode() {
    const body = document.body;
    const isDarkMode = body.getAttribute('data-theme') === 'dark';
    const newTheme = isDarkMode ? 'light' : 'dark';
    body.setAttribute('data-theme', newTheme);
    updateDarkModeIcon(newTheme);
    localStorage.setItem('darkMode', newTheme);
    showToast(`Switched to ${newTheme} mode`, 'info', 2000);
}

export function updateDarkModeIcon(theme) {
    const icon = document.getElementById('darkModeIcon');
    if (!icon) return;
    if (theme === 'dark') {
        icon.innerHTML = `<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>`;
    } else {
        icon.innerHTML = `<circle cx="12" cy="12" r="5"></circle><path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72 1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"></path>`;
    }
}

export function initializeDarkMode() {
    const savedTheme = localStorage.getItem('darkMode');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = savedTheme || (prefersDark ? 'dark' : 'light');
    document.body.setAttribute('data-theme', theme);
    updateDarkModeIcon(theme);
}
