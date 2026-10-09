(() => {
  function injectStyle() {
    if (document.querySelector('#add-to-controls-style')) return;
    const style = document.createElement('style');
    style.id = 'add-to-controls-style';
    style.textContent = `
      .history-add-to {
        min-height:36px;
        padding:7px 10px;
        border:1px solid color-mix(in srgb,var(--warm-accent) 45%,var(--line-strong));
        background:color-mix(in srgb,var(--accent-deeper) 48%,var(--control));
        color:var(--warm-accent);
        font:500 11px/1.4 'DM Mono',monospace;
        text-transform:uppercase;
        letter-spacing:.04em;
      }
      .history-add-to:hover {
        color:var(--button-ink);
        border-color:var(--warm-accent);
        background:var(--warm-accent);
      }
      .history-add-to[disabled] { cursor:wait; opacity:.72; }
      @media (max-width:700px) { .history-add-to { min-height:40px; } }
    `;
    document.head.appendChild(style);
  }

  function enhance() {
    injectStyle();
    document.querySelectorAll('.playlist').forEach(article => {
      const actions = article.querySelector('.actions');
      const regen = actions?.querySelector('.regen');
      if (!actions || !regen || actions.querySelector('.history-add-to')) return;
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'history-add-to';
      button.dataset.id = regen.dataset.id || '';
      button.textContent = 'Add to';
      button.title = 'Scan the current Spotify playlist and append more tracks that fit';
      const refine = actions.querySelector('.history-refine');
      if (refine) actions.insertBefore(button, refine);
      else actions.appendChild(button);
    });
  }

  function reportFailure(details) {
    const status = document.querySelector('#status');
    const summary = 'ADD TO FAILED / ' + details.message;
    if (status) status.textContent = summary;
    let panel = document.querySelector('#add-to-error-details');
    if (!panel) {
      panel = document.createElement('details');
      panel.id = 'add-to-error-details';
      panel.style.cssText = 'margin:12px 0;padding:12px;border:1px solid var(--line-strong);white-space:pre-wrap;overflow-wrap:anywhere';
      const summaryNode = document.createElement('summary');
      summaryNode.textContent = 'View error diagnostics';
      const pre = document.createElement('pre');
      pre.style.cssText = 'white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px';
      panel.append(summaryNode, pre);
      (status?.parentNode || document.body).appendChild(panel);
    }
    panel.querySelector('pre').textContent = JSON.stringify(details, null, 2);
    panel.hidden = false;
    panel.open = true;
    console.error('[Tune Raider] Add to failed', details);
  }

  async function addMore(button) {
    const id = button.dataset.id;
    if (!id || button.disabled) return;
    const original = button.textContent;
    const startedAt = Date.now();
    const endpoint = `/api/history/${encodeURIComponent(id)}/add`;
    document.querySelector('#add-to-error-details')?.remove();
    const status = document.querySelector('#status');
    button.disabled = true;
    button.textContent = 'Adding…';
    if (status) status.textContent = 'SYNCING SPOTIFY / DISCOVERING / ADDING...';
    let response;
    let responseBody = '';
    let data = {};
    try {
      response = await fetch(endpoint, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:'{}',
      });
      responseBody = await response.text();
      try { data = JSON.parse(responseBody); } catch (_) {}
      if (!response.ok) {
        const reason = response.status === 524
          ? 'Cloudflare timed out waiting for Tune Raider. The server may still be processing; check Spotify and history before retrying.'
          : (data.error || 'Could not add tracks.');
        throw new Error(reason);
      }
      if (data.notice) window.alert(data.notice);
      window.location.reload();
    } catch (error) {
      button.disabled = false;
      button.textContent = original;
      reportFailure({
        operation: 'Add to playlist',
        historyId: id,
        endpoint,
        timestamp: new Date().toISOString(),
        elapsedSeconds: Math.round((Date.now() - startedAt) / 1000),
        httpStatus: response?.status ?? null,
        httpStatusText: response?.statusText || null,
        errorType: error?.name || 'Error',
        message: String(error?.message || error),
        serverError: data.error || null,
        serverStage: data.stage || null,
        requestId: response?.headers?.get('cf-ray') || null,
        responseExcerpt: responseBody.slice(0, 1200) || null,
        guidance: response?.status === 524
          ? 'Do not immediately retry. The backend may have finished writing to Spotify even though Cloudflare timed out.'
          : 'Review the activity log and server logs for additional details.',
      });
    }
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('.history-add-to');
    if (button) addMore(button);
  });

  const boot = () => {
    enhance();
    const history = document.querySelector('#history');
    if (history) new MutationObserver(enhance).observe(history, {childList:true, subtree:true});
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
