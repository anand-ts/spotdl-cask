import { installSelectionShortcuts } from './selection.js';
import { setRowActionHandlers } from './rows.js';
import {
    installDownloadControls,
    installPasteHandler,
    startStatusPolling,
    dlOne,
    cancelOne,
    showInFinder
} from './downloads.js';
import {
    applySettings,
    closeSettings,
    loadServerSettings,
    openSettingsFromPrompt,
    pickDownloadDirectory,
    toggleSettings
} from './settings.js';
import { setupDragAndDrop } from './appearance.js';
import {
    initializeCompactMode,
    initializeDarkMode,
    setHeaderIdle,
    startIdleMonitor,
    toggleCompactMode,
    toggleDarkMode
} from './ui.js';
import { updateCancelAllButtonState, updateDownloadAllButtonState } from './controls.js';

export async function initializeApp() {
    setRowActionHandlers({ dlOne, cancelOne, showInFinder });
    installSelectionShortcuts();
    installDownloadControls();
    installPasteHandler();
    startStatusPolling();
    startIdleMonitor();

    window.toggleCompactMode = toggleCompactMode;
    window.toggleDarkMode = toggleDarkMode;
    window.toggleSettings = toggleSettings;
    window.pickDownloadDirectory = pickDownloadDirectory;
    window.openSettingsFromPrompt = openSettingsFromPrompt;
    window.closeSettings = closeSettings;
    window.applySettings = applySettings;

    initializeCompactMode();
    initializeDarkMode();
    setupDragAndDrop();
    await loadServerSettings();
    updateDownloadAllButtonState();
    updateCancelAllButtonState();
    setHeaderIdle(true);
}
