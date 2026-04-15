import { ph } from './dom.js';
import { addRow } from './rows.js';
import { showToast } from './ui.js';

export function setupDragAndDrop() {
    const dropZone = ph;

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, event => {
            event.preventDefault();
            event.stopPropagation();
        }, false);
        document.body.addEventListener(eventName, event => {
            event.preventDefault();
            event.stopPropagation();
        }, false);
    });

    ['dragenter', 'dragover'].forEach(eventName =>
        dropZone.addEventListener(eventName, () => dropZone.classList.add('drag-over'), false)
    );
    ['dragleave', 'drop'].forEach(eventName =>
        dropZone.addEventListener(eventName, () => dropZone.classList.remove('drag-over'), false)
    );

    dropZone.addEventListener('drop', event => {
        const text = event.dataTransfer.getData('text');
        if (!text) return;

        const links = text.split(/[\s,]+/).filter(token => token.startsWith('http'));
        if (!links.length) return;

        showToast(`Processing ${links.length} link${links.length > 1 ? 's' : ''}...`, 'info');
        links.forEach(addRow);
    }, false);
}
