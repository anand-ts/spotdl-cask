import { initializeApp } from './modules/bootstrap.js';

document.addEventListener('DOMContentLoaded', () => {
    initializeApp().catch(error => {
        console.error('App initialization failed:', error);
    });
});
