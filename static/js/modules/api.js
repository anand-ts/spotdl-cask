async function parseJsonResponse(response, fallbackMessage) {
    let payload = {};
    try {
        payload = await response.json();
    } catch (_error) {
        payload = {};
    }

    if (!response.ok) {
        throw new Error(payload.error || fallbackMessage);
    }

    return payload;
}

export async function fetchSettings() {
    const response = await fetch('/settings');
    return parseJsonResponse(response, 'Failed to load saved settings.');
}

export async function pickDownloadDirectoryRequest(source = 'settings') {
    const response = await fetch('/settings/download-directory/pick', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source })
    });
    return parseJsonResponse(response, 'Could not choose a download folder.');
}

export async function fetchMetadata(link) {
    const response = await fetch('/meta', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link })
    });
    return parseJsonResponse(response, 'Failed to load track metadata');
}

export async function startDownloadRequest(link, settings) {
    const response = await fetch('/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link, ...settings })
    });

    if (response.ok) {
        return {};
    }

    return parseJsonResponse(response, 'Download failed to start.');
}

export async function cancelDownloadRequest(link) {
    const response = await fetch('/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link })
    });

    if (!response.ok) {
        throw new Error('Failed to cancel download');
    }
}

export async function revealDownloadRequest(link) {
    const response = await fetch('/reveal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ link })
    });
    return parseJsonResponse(response, 'Could not reveal the downloaded file.');
}

export async function fetchStatuses(links) {
    const response = await fetch('/status?links=' + encodeURIComponent(links.join(',')));
    return response.json();
}
