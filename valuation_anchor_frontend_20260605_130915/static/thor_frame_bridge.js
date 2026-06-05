(function () {
    if (window.__reviewsDailyThorFrameBridgeLoaded) return;
    window.__reviewsDailyThorFrameBridgeLoaded = true;

    function isThorShortcutEvent(event) {
        if (!event || event.isComposing) return false;
        var key = String(event.key || '').toLowerCase();
        var code = String(event.code || '').toLowerCase();
        return (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey &&
            (key === 'k' || code === 'keyk');
    }

    function openHostThorPanel() {
        try {
            if (window.parent && window.parent !== window && typeof window.parent.__reviewsDailyOpenThorPanel === 'function') {
                window.parent.__reviewsDailyOpenThorPanel();
                return true;
            }
        } catch (error) {}
        return false;
    }

    function handleThorShortcut(event) {
        if (!isThorShortcutEvent(event) || event.__rdThorShortcutHandled) return;
        if (!openHostThorPanel()) return;
        event.__rdThorShortcutHandled = true;
        event.preventDefault();
        event.stopPropagation();
        if (event.stopImmediatePropagation) event.stopImmediatePropagation();
    }

    try {
        window.addEventListener('keydown', handleThorShortcut, true);
        document.addEventListener('keydown', handleThorShortcut, true);
    } catch (error) {}
})();
