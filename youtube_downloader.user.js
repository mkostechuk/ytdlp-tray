// ==UserScript==
// @name         YouTube yt-dlp Downloader
// @namespace    http://tampermonkey.net/
// @version      2.0
// @description  Adds a Download button to YouTube video & Shorts pages calling a local yt-dlp API
// @author       miko
// @match        https://www.youtube.com/*
// @grant        GM_xmlhttpRequest
// @connect      localhost
// @run-at       document-idle
// @noframes
// ==/UserScript==

(function () {
    'use strict';

    const API_URL    = 'http://localhost:9876/download';
    const STATUS_URL = 'http://localhost:9876/status';
    const BTN_ID     = 'ytdlp-download-btn';

    // ── Styles ────────────────────────────────────────────────────────────
    const BASE = `
        display:inline-flex; align-items:center; justify-content:center;
        border:none; border-radius:18px; cursor:pointer;
        font-family:"Roboto",sans-serif; font-weight:500; font-size:14px;
        letter-spacing:.3px; transition:opacity .15s, background .3s;
        white-space:nowrap;
    `.replace(/\s+/g, ' ');

    function sizeStyle(isShorts) {
        return isShorts
            ? 'height:40px; min-width:40px; padding:0 12px;'
            : 'height:36px; min-width:36px; padding:0 10px; margin-left:8px;';
    }

    function applyStyle(btn, bg, color, fontSize) {
        btn.style.cssText = BASE + `background:${bg};color:${color};font-size:${fontSize};` + sizeStyle(btn._isShorts);
    }

    function setIdle(btn)         { btn.textContent = '⬇';       applyStyle(btn, '#ffffff', '#000000', '20px'); btn.disabled = false; }
    function setProgress(btn, pct){ btn.textContent = `${pct}%`;     applyStyle(btn, '#c8a800', '#333', '13px'); btn.disabled = true;  }
    function setDone(btn)         { btn.textContent = '✔';       applyStyle(btn, '#1a8a1a', '#fff', '20px'); btn.disabled = false; }
    function setError(btn)        { btn.textContent = '✘';       applyStyle(btn, '#b00020', '#fff', '20px'); btn.disabled = false; }

    // ── Polling ───────────────────────────────────────────────────────────
    let _pollTimer = null;

    function startPolling(btn, url) {
        stopPolling();
        _pollTimer = setInterval(() => {
            GM_xmlhttpRequest({
                method: 'GET',
                url: STATUS_URL + '?url=' + encodeURIComponent(url),
                timeout: 3000,
                onload(r) {
                    if (r.status !== 200) return;
                    let data;
                    try { data = JSON.parse(r.responseText); } catch { return; }

                    if (data.status === 'downloading') {
                        setProgress(btn, Math.floor(data.percent));
                    } else if (data.status === 'done') {
                        stopPolling();
                        setDone(btn);
                    } else if (data.status === 'error') {
                        stopPolling();
                        setError(btn);
                    }
                },
                onerror() { stopPolling(); setError(btn); },
            });
        }, 1000);
    }

    function stopPolling() {
        if (_pollTimer !== null) { clearInterval(_pollTimer); _pollTimer = null; }
    }

    // ── Page type helpers ─────────────────────────────────────────────────
    function isWatch()  { return location.pathname === '/watch'; }
    function isShorts() { return location.pathname.startsWith('/shorts/'); }

    // ── Button creation ───────────────────────────────────────────────────
    function createButton(shorts) {
        const btn = document.createElement('button');
        btn.id = BTN_ID;
        btn._isShorts = shorts;
        setIdle(btn);

        btn.addEventListener('mouseenter', () => { if (!btn.disabled) btn.style.opacity = '.82'; });
        btn.addEventListener('mouseleave', () => { btn.style.opacity = '1'; });

        btn.addEventListener('click', () => {
            if (btn.disabled) return;
            const url = location.href.split('&')[0];
            setProgress(btn, 0);

            GM_xmlhttpRequest({
                method: 'POST',
                url: API_URL,
                headers: { 'Content-Type': 'application/json' },
                data: JSON.stringify({ url }),
                timeout: 8000,
                onload(r) {
                    if (r.status >= 200 && r.status < 300) {
                        startPolling(btn, url);
                    } else {
                        setError(btn);
                        setTimeout(() => setIdle(btn), 3000);
                    }
                },
                onerror()   { setError(btn); setTimeout(() => setIdle(btn), 3000); },
                ontimeout() { setError(btn); setTimeout(() => setIdle(btn), 3000); },
            });
        });

        return btn;
    }

    // ── Injection: regular watch page ─────────────────────────────────────
    function injectWatch() {
        if (document.getElementById(BTN_ID)) return;

        // #owner is the flex row containing the channel name + subscribe button
        const meta = document.querySelector('ytd-watch-metadata');
        if (!meta) return;

        const ownerRow = meta.querySelector('#owner');
        if (!ownerRow) return;

        const subscribeDiv = ownerRow.querySelector('#subscribe-button');
        if (!subscribeDiv) return;

        const btn = createButton(false);
        btn.style.alignSelf = 'center';
        ownerRow.insertBefore(btn, subscribeDiv.nextSibling);
    }

    // ── Injection: Shorts ─────────────────────────────────────────────────
    function injectShorts() {
        if (document.getElementById(BTN_ID)) return;

        // Shorts action buttons panel (like / dislike / share / remix …)
        const panel =
            document.querySelector('ytd-reel-video-renderer[is-active] #actions') ||
            document.querySelector('#actions.ytd-reel-player-overlay-renderer') ||
            document.querySelector('ytd-shorts #actions');
        if (!panel) return;

        const btn = createButton(true);
        // Insert at the top of the action panel so it's immediately visible
        panel.insertBefore(btn, panel.firstChild);
    }

    // ── Main injection dispatcher ─────────────────────────────────────────
    function tryInject() {
        if (isWatch())  injectWatch();
        if (isShorts()) injectShorts();
    }

    // ── SPA navigation handling ───────────────────────────────────────────
    let lastUrl = location.href;

    const observer = new MutationObserver(() => {
        const cur = location.href;
        if (cur !== lastUrl) {
            lastUrl = cur;
            stopPolling();
            document.getElementById(BTN_ID)?.remove();
        }
        tryInject();
    });

    observer.observe(document.body, { childList: true, subtree: true });
    tryInject(); // also run immediately on page load

})();