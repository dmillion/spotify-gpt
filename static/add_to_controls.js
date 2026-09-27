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

  async function addMore(button) {
    const id = button.dataset.id;
    if (!id || button.disabled) return;
    const original = button.textContent;
    const status = document.querySelector('#status');
    button.disabled = true;
    button.textContent = 'Adding…';
    if (status) status.textContent = 'SYNCING SPOTIFY / DISCOVERING / ADDING...';
    try {
      const response = await fetch(`/api/history/${encodeURIComponent(id)}/add`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:'{}',
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Could not add tracks.');
      if (data.notice) window.alert(data.notice);
      window.location.reload();
    } catch (error) {
      button.disabled = false;
      button.textContent = original;
      if (status) status.textContent = `ERROR / ${error.message || error}`;
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
