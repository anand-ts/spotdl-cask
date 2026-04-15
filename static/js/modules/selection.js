import { tblBody } from './dom.js';
import { state } from './state.js';
import { markActivity, showToast } from './ui.js';

function isEditableTarget(target) {
    if (!(target instanceof Element)) {
        return false;
    }

    return Boolean(
        target.closest('input, textarea, select, [contenteditable], [contenteditable="true"]')
    );
}

function getRowLinksInOrder() {
    return Array.from(tblBody.querySelectorAll('tr[data-link]'))
        .map(row => row.dataset.link)
        .filter(link => Boolean(link) && Boolean(state.rows[link]));
}

export function getSelectedLinksInOrder() {
    return getRowLinksInOrder().filter(link => state.selectedLinks.has(link));
}

function focusRow(link) {
    const row = state.rows[link];
    if (!row || typeof row.focus !== 'function') return;
    row.focus({ preventScroll: true });
}

export function syncRowSelection(link) {
    const row = state.rows[link];
    if (!row) return;

    const isSelected = state.selectedLinks.has(link);
    row.classList.toggle('selected-row', isSelected);
    row.setAttribute('aria-selected', isSelected ? 'true' : 'false');
}

function setSelectedLinks(links, { anchorLink = null } = {}) {
    const nextSelectedLinks = new Set(links.filter(link => state.rows[link]));
    const touchedLinks = new Set([...state.selectedLinks, ...nextSelectedLinks]);

    touchedLinks.forEach(link => {
        if (nextSelectedLinks.has(link)) {
            state.selectedLinks.add(link);
        } else {
            state.selectedLinks.delete(link);
        }
        syncRowSelection(link);
    });

    if (nextSelectedLinks.size === 0) {
        state.selectionAnchorLink = null;
        return;
    }

    state.selectionAnchorLink = anchorLink;
}

export function clearSelectedRows() {
    setSelectedLinks([]);
}

function getSelectionRange(anchorLink, targetLink) {
    const orderedLinks = getRowLinksInOrder();
    const anchorIndex = orderedLinks.indexOf(anchorLink);
    const targetIndex = orderedLinks.indexOf(targetLink);

    if (anchorIndex === -1 || targetIndex === -1) {
        return targetLink ? [targetLink] : [];
    }

    const start = Math.min(anchorIndex, targetIndex);
    const end = Math.max(anchorIndex, targetIndex);
    return orderedLinks.slice(start, end + 1);
}

export function handleRowSelection(event, link) {
    if (!state.rows[link]) return;

    markActivity();

    if (event.shiftKey) {
        const anchorLink = state.selectionAnchorLink && state.rows[state.selectionAnchorLink]
            ? state.selectionAnchorLink
            : link;
        setSelectedLinks(getSelectionRange(anchorLink, link), { anchorLink });
        focusRow(link);
        return;
    }

    if (event.metaKey || event.ctrlKey) {
        const nextSelectedLinks = new Set(state.selectedLinks);
        if (nextSelectedLinks.has(link)) {
            nextSelectedLinks.delete(link);
        } else {
            nextSelectedLinks.add(link);
        }

        setSelectedLinks(
            getRowLinksInOrder().filter(currentLink => nextSelectedLinks.has(currentLink)),
            { anchorLink: link }
        );
        focusRow(link);
        return;
    }

    setSelectedLinks([link], { anchorLink: link });
    focusRow(link);
}

async function copyTextToClipboard(text) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
        try {
            await navigator.clipboard.writeText(text);
            return;
        } catch (error) {
            console.warn('Clipboard API copy failed, falling back to execCommand:', error);
        }
    }

    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.top = '0';
    textarea.style.left = '0';
    textarea.style.opacity = '0';
    textarea.style.pointerEvents = 'none';

    const activeElement = document.activeElement;
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();

    let copied = false;
    try {
        copied = document.execCommand('copy');
    } finally {
        document.body.removeChild(textarea);
        if (activeElement instanceof HTMLElement && typeof activeElement.focus === 'function') {
            activeElement.focus({ preventScroll: true });
        }
    }

    if (!copied) {
        throw new Error('Copy failed.');
    }
}

async function copySelectedLinks() {
    const links = getSelectedLinksInOrder();
    if (!links.length) {
        return false;
    }

    await copyTextToClipboard(links.join('\n'));
    showToast(`Copied ${links.length} link${links.length > 1 ? 's' : ''}`, 'success', 2200);
    return true;
}

export function removeSelectionForLink(link) {
    state.selectedLinks.delete(link);
    if (state.selectionAnchorLink === link) {
        state.selectionAnchorLink = null;
    }
}

export function installSelectionShortcuts() {
    document.addEventListener('keydown', event => {
        const key = event.key.toLowerCase();
        const modifierPressed = event.metaKey || event.ctrlKey;

        if (modifierPressed && key === 'a') {
            if (isEditableTarget(event.target)) return;

            const links = getRowLinksInOrder();
            if (!links.length) return;

            event.preventDefault();
            markActivity();
            setSelectedLinks(links, { anchorLink: links[0] });
            focusRow(links[0]);
            return;
        }

        if (modifierPressed && key === 'c') {
            if (isEditableTarget(event.target) || state.selectedLinks.size === 0) return;

            event.preventDefault();
            markActivity();
            copySelectedLinks().catch(error => {
                console.error('Copy failed:', error);
                showToast(error.message || 'Could not copy selected links.', 'error', 3500);
            });
            return;
        }

        if (key === 'escape' && state.selectedLinks.size > 0 && !isEditableTarget(event.target)) {
            clearSelectedRows();
        }
    });
}
