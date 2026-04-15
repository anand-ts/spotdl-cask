import {
    downloadDirPrompt,
    downloadDirPromptPath,
    downloadDirSel,
    downloadDirStatus,
    overlay,
    sidebar
} from './dom.js';
import { pickDownloadDirectoryRequest, fetchSettings } from './api.js';
import { state, hasDownloadDirectory, normalizeDownloadDirectory } from './state.js';
import { markActivity, showToast } from './ui.js';
import { updateDownloadAvailability } from './controls.js';

export function syncDownloadDirectoryUI() {
    const downloadDirectory = normalizeDownloadDirectory(state.settings.downloadDirectory);

    if (downloadDirSel) {
        downloadDirSel.value = downloadDirectory;
    }

    if (downloadDirPromptPath) {
        downloadDirPromptPath.textContent = downloadDirectory || 'No folder selected yet';
    }

    if (downloadDirStatus) {
        downloadDirStatus.textContent = downloadDirectory ? 'Configured' : 'Required';
        downloadDirStatus.classList.toggle('configured', Boolean(downloadDirectory));
    }

    if (downloadDirPrompt) {
        const shouldShow = state.settingsLoaded && !downloadDirectory;
        downloadDirPrompt.classList.toggle('show', shouldShow);
        downloadDirPrompt.setAttribute('aria-hidden', shouldShow ? 'false' : 'true');
    }

    updateDownloadAvailability();
}

export function ensureDownloadDirectoryConfigured() {
    if (hasDownloadDirectory()) {
        return true;
    }

    syncDownloadDirectoryUI();
    showToast('Choose a download folder before starting downloads.', 'info', 3500);
    return false;
}

export async function loadServerSettings() {
    try {
        const data = await fetchSettings();
        state.settings.downloadDirectory = normalizeDownloadDirectory(data.downloadDirectory);
    } catch (error) {
        console.error('Settings load failed:', error);
        showToast(error.message || 'Failed to load saved settings.', 'error', 4000);
    } finally {
        state.settingsLoaded = true;
        syncDownloadDirectoryUI();
    }
}

export async function pickDownloadDirectory({ source = 'settings' } = {}) {
    markActivity();

    try {
        const data = await pickDownloadDirectoryRequest(source);
        if (data.cancelled) {
            if (!hasDownloadDirectory()) {
                syncDownloadDirectoryUI();
                showToast('Choose a download folder to continue.', 'info', 3500);
            }
            return false;
        }

        state.settings.downloadDirectory = normalizeDownloadDirectory(data.downloadDirectory);
        syncDownloadDirectoryUI();
        showToast(`Download folder set to ${state.settings.downloadDirectory}`, 'success', 3500);
        return true;
    } catch (error) {
        console.error('Folder picker failed:', error);
        showToast(error.message || 'Could not choose a download folder.', 'error', 4000);
        return false;
    }
}

export function toggleSettings() {
    markActivity();
    sidebar.classList.add('open');
    overlay.classList.add('show');
}

export function openSettingsFromPrompt() {
    markActivity();
    if (downloadDirPrompt) {
        downloadDirPrompt.classList.remove('show');
        downloadDirPrompt.setAttribute('aria-hidden', 'true');
    }
    toggleSettings();
}

export function closeSettings() {
    sidebar.classList.remove('open');
    overlay.classList.remove('show');
    syncDownloadDirectoryUI();
}

export function applySettings() {
    const qualityRadio = document.querySelector('input[name="quality"]:checked');
    state.settings.downloadDirectory = normalizeDownloadDirectory(downloadDirSel ? downloadDirSel.value : state.settings.downloadDirectory);
    state.settings.quality = qualityRadio ? qualityRadio.value : 'best';
    state.settings.format = document.getElementById('formatSel').value;
    state.settings.output = document.getElementById('outputSel').value;
    state.settings.playlistNumbering = document.getElementById('playlistNumbering').checked;
    state.settings.skipExplicit = document.getElementById('skipExplicit').checked;
    state.settings.generateLrc = document.getElementById('generateLrc').checked;

    if (!hasDownloadDirectory()) {
        syncDownloadDirectoryUI();
        showToast('Choose a download folder first.', 'error', 3500);
        return;
    }

    closeSettings();
    showToast('Settings saved successfully!', 'success', 3000);
    console.log('Applied settings:', state.settings);
}
