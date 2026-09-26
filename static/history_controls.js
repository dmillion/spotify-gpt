(() => {
  const EMPTY_HISTORY = '<div class="empty">No playlists yet. Give the machine a mood.</div>';
  let pendingBuildNotice = '';

  if (!document.querySelector('script[data-tune-raider-activity]')) {
    const activityScript = document.createElement('script');
    activityScript.src = '/static/activity_terminal.js';
    activityScript.dataset.tuneRaiderActivity = 'true';
    document.head.appendChild(activityScript);
  }

  // The original inline generator owns the main request flow. Capture optional
  // backend notices without replacing that flow, then append them to its status.
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await nativeFetch(...args);
    const url = String(args[0]?.url || args[0] || '');
    if (response.ok && (/\/api\/generate(?:\?|$)/.test(url) || /\/api\/history\/\d+\/regenerate(?:\?|$)/.test(url))) {
      try {
        const data = await response.clone().json();
        pendingBuildNotice = String(data.notice || '').trim();
      } catch (_) {
        pendingBuildNotice = '';
      }
    }
    return response;
  };

  function injectStyles() {
    if (document.querySelector('#history-controls-style')) return;
    const style = document.createElement('style');
    style.id = 'history-controls-style';
    style.textContent = `
      :root {
        --history-accent-mid:#6fbf98;
        --history-accent-dark:#356b57;
        --history-accent-deep:#21473a;
        --history-text-strong:#e7f3ed;
        --history-text-body:#bdd0c7;
        --history-text-muted:#8fa59b;
        --history-text-faint:#6f867c;
        --history-panel-border:rgba(111,191,152,.22);
        --history-panel-fill:rgba(20,42,35,.22);
        --history-panel-fill-strong:rgba(20,42,35,.34);
      }
      html[data-theme='amber'] {
        --history-accent-mid:#c49b61;
        --history-accent-dark:#725633;
        --history-accent-deep:#43321e;
        --history-text-strong:#fff1dc;
        --history-text-body:#dbc4a1;
        --history-text-muted:#b49c7b;
        --history-text-faint:#8c7659;
        --history-panel-border:rgba(196,155,97,.22);
        --history-panel-fill:rgba(70,49,26,.22);
        --history-panel-fill-strong:rgba(70,49,26,.34);
      }

      .history-panel .section-head h2 { color:var(--history-text-strong); }
      .history-head-actions { display:flex; align-items:center; gap:12px; }
      .history-head-actions #count { color:var(--history-text-muted); }

      .playlist {
        position:relative;
        margin:0;
        padding:28px 18px 30px;
        border-top:1px solid var(--history-panel-border);
        background:linear-gradient(180deg,var(--history-panel-fill),transparent 88%);
        box-shadow:inset 2px 0 0 var(--history-accent-deep);
      }
      .playlist + .playlist { margin-top:4px; }
      .playlist:last-child { border-bottom:1px solid var(--history-panel-border); }
      .playlist .eyebrow {
        color:var(--history-accent-mid) !important;
        opacity:.9;
        letter-spacing:.075em !important;
      }
      .playlist h3 {
        color:var(--history-text-strong);
        text-shadow:0 0 14px rgba(111,191,152,.08);
      }
      .playlist p {
        color:var(--history-text-body);
        line-height:1.6;
      }
      .playlist .date { color:var(--history-text-muted); }

      .playlist .tracks {
        display:flex;
        flex-wrap:wrap;
        gap:8px;
        margin-top:16px;
      }
      .playlist .track {
        display:inline-flex;
        align-items:center;
        min-height:30px;
        padding:5px 9px;
        border:1px solid var(--history-panel-border);
        border-left:1px solid var(--history-accent-dark);
        background:var(--history-panel-fill-strong);
        color:var(--history-text-body);
        line-height:1.35;
        transition:border-color 140ms ease-out,background-color 140ms ease-out,color 140ms ease-out;
      }
      .playlist .track:hover {
        color:var(--history-text-strong);
        border-color:var(--history-accent-mid);
        background:color-mix(in srgb,var(--history-panel-fill-strong) 75%,var(--history-accent-deep));
      }
      .playlist .tracks .meta,
      .playlist .tracks .more-count { color:var(--acid); }

      .playlist .actions a {
        color:var(--acid);
        border-bottom:1px solid color-mix(in srgb,var(--acid) 42%,transparent);
      }
      .playlist .actions a:hover {
        color:var(--history-text-strong);
        border-bottom-color:var(--acid);
      }

      .history-clear,
      .history-remove,
      .history-refine,
      .history-refine-apply,
      .history-refine-cancel {
        min-height:36px;
        padding:7px 10px;
        border:1px solid var(--line-strong);
        background:transparent;
        color:var(--muted);
        font:500 11px/1.4 'DM Mono',monospace;
        text-transform:uppercase;
        letter-spacing:.04em;
      }
      .regen {
        color:var(--history-text-strong) !important;
        border-color:var(--history-accent-mid) !important;
        background:color-mix(in srgb,var(--history-accent-deep) 38%,var(--control)) !important;
      }
      .regen:hover {
        color:var(--button-ink) !important;
        border-color:var(--acid) !important;
        background:var(--acid) !important;
      }
      .history-refine {
        color:var(--history-text-body);
        border-color:var(--history-panel-border);
      }
      .history-refine:hover,
      .history-refine-apply:hover {
        color:var(--button-ink);
        border-color:var(--acid);
        background:var(--acid);
      }
      .history-clear {
        color:var(--history-text-body);
        border-color:var(--history-panel-border);
      }
      .history-clear:hover {
        color:var(--history-text-strong);
        border-color:var(--history-accent-mid);
        background:var(--history-panel-fill);
      }
      .history-remove {
        color:var(--history-text-muted);
        border-color:color-mix(in srgb,var(--history-text-muted) 28%,transparent);
      }
      .history-remove:hover {
        color:var(--red);
        border-color:var(--red);
        background:color-mix(in srgb,var(--red) 8%,transparent);
      }
      .history-refine-cancel:hover {
        color:var(--ink);
        border-color:var(--muted);
      }
      .history-clear[hidden],
      .history-refine-form[hidden],
      .history-refine-status[hidden] { display:none; }
      .history-refine-form {
        grid-column:1 / -1;
        display:grid;
        grid-template-columns:minmax(0,1fr) auto auto;
        gap:8px;
        align-items:end;
        margin-top:14px;
        padding:12px;
        border-left:2px solid var(--history-accent-dark);
        background:var(--control);
      }
      .history-refine-form label {
        display:grid;
        gap:6px;
        color:var(--muted);
        font:500 11px/1.4 'DM Mono',monospace;
        text-transform:uppercase;
        letter-spacing:.04em;
      }
      .history-refine-input {
        width:100%;
        min-height:70px;
        resize:vertical;
        padding:10px 12px;
        border:1px solid var(--line);
        background:var(--surface);
        color:var(--ink);
        font:13px/1.5 'DM Mono',monospace;
      }
      .history-refine-form.is-working .history-refine-input,
      .history-refine-form.is-working .history-refine-cancel { opacity:.45; }
      .history-refine-form.is-working .history-refine-apply {
        cursor:wait;
        color:var(--button-ink);
        border-color:var(--acid);
        background:var(--acid);
      }
      .history-refine-status {
        grid-column:1 / -1;
        display:flex;
        align-items:center;
        gap:9px;
        min-height:28px;
        padding:5px 0 1px;
        color:var(--acid);
        font:500 11px/1.5 'DM Mono',monospace;
        text-transform:uppercase;
        letter-spacing:.05em;
      }
      .history-refine-spinner {
        width:12px;
        height:12px;
        flex:0 0 12px;
        border:1px solid var(--line-strong);
        border-top-color:var(--acid);
        border-right-color:var(--acid);
        border-radius:50%;
        animation:history-refine-spin .7s linear infinite;
        box-shadow:0 0 6px var(--glow);
      }
      @keyframes history-refine-spin { to { transform:rotate(360deg); } }
      @media (max-width:700px) {
        .history-head-actions { gap:8px; }
        .playlist { padding:22px 12px 24px; }
        .history-clear,
        .history-remove,
        .history-refine,
        .history-refine-apply,
        .history-refine-cancel { min-height:40px; }
        .history-refine-form { grid-template-columns:1fr 1fr; }
        .history-refine-form label { grid-column:1 / -1; }
      }
    `;
    document.head.appendChild(style);
  }

  function syncCount() {
    const history = document.querySelector('#history');
    const count = document.querySelector('#count');
    const clearButton = document.querySelector('.history-clear');
    if (!history || !count) return;
    const total = history.querySelectorAll('.playlist').length;
    count.textContent = `${total} saved`;
    if (clearButton) clearButton.hidden = total === 0;
    if (total === 0 && !history.querySelector('.empty')) history.innerHTML = EMPTY_HISTORY;
  }

  function enhanceHistory() {
    const history = document.querySelector('#history');
    const sectionHead = document.querySelector('.history-panel .section-head');
    const count = document.querySelector('#count');
    if (!history || !sectionHead || !count) return;

    let headActions = sectionHead.querySelector('.history-head-actions');
    if (!headActions) {
      headActions = document.createElement('div');
      headActions.className = 'history-head-actions';
      count.replaceWith(headActions);
      headActions.appendChild(count);

      const clearButton = document.createElement('button');
      clearButton.type = 'button';
      clearButton.className = 'history-clear';
      clearButton.textContent = 'Clear history';
      clearButton.title = 'Remove all playlists from Tune Raider history only';
      headActions.appendChild(clearButton);
    }

    history.querySelectorAll('.playlist').forEach(article => {
      const actions = article.querySelector('.actions');
      const regen = actions?.querySelector('.regen');
      if (!actions || !regen) return;
      const id = regen.dataset.id || '';

      if (!actions.querySelector('.history-refine')) {
        const refineButton = document.createElement('button');
        refineButton.type = 'button';
        refineButton.className = 'history-refine';
        refineButton.dataset.id = id;
        refineButton.textContent = 'Refine';
        refineButton.title = 'Create a revised version from another prompt';
        actions.appendChild(refineButton);
      }

      if (!actions.querySelector('.history-remove')) {
        const removeButton = document.createElement('button');
        removeButton.type = 'button';
        removeButton.className = 'history-remove';
        removeButton.dataset.id = id;
        removeButton.textContent = 'Remove';
        removeButton.title = 'Remove from Tune Raider history only';
        actions.appendChild(removeButton);
      }

      if (!article.querySelector('.history-refine-form')) {
        const form = document.createElement('div');
        form.className = 'history-refine-form';
        form.hidden = true;
        form.dataset.id = id;
        form.innerHTML = `
          <label>Refinement prompt
            <textarea class="history-refine-input" placeholder="e.g. remove the hip-hop tracks; add 5 slower doom songs; make the back half heavier"></textarea>
          </label>
          <button type="button" class="history-refine-apply">Apply</button>
          <button type="button" class="history-refine-cancel">Cancel</button>
          <div class="history-refine-status" role="status" aria-live="polite" hidden>
            <span class="history-refine-spinner" aria-hidden="true"></span>
            <span class="history-refine-status-text">Planning refinement…</span>
          </div>
        `;
        article.appendChild(form);
      }
    });

    syncCount();
  }

  function toggleRefine(button) {
    const article = button.closest('.playlist');
    const form = article?.querySelector('.history-refine-form');
    if (!form) return;
    form.hidden = !form.hidden;
    if (!form.hidden) form.querySelector('.history-refine-input')?.focus();
  }

  async function applyRefinement(button) {
    const form = button.closest('.history-refine-form');
    const input = form?.querySelector('.history-refine-input');
    const id = form?.dataset.id;
    const instruction = input?.value?.trim() || '';
    if (!form || !id || !instruction) {
      window.alert('Describe what you want to change first.');
      return;
    }

    const inlineStatus = form.querySelector('.history-refine-status');
    const inlineStatusText = form.querySelector('.history-refine-status-text');
    const terminal = document.querySelector('.network-terminal');
    const originalButtonText = button.textContent;
    let stageTimer = null;

    form.classList.add('is-working');
    button.disabled = true;
    button.textContent = 'Applying…';
    if (inlineStatus) inlineStatus.hidden = false;
    if (inlineStatusText) inlineStatusText.textContent = 'Planning refinement…';
    if (terminal) terminal.dataset.active = 'true';

    const status = document.querySelector('#status');
    if (status) status.textContent = 'REFINING / CURATING / RESOLVING...';

    // Refinement can take a while with a local model. Keep the nearby status
    // visibly changing so it never looks like the Apply click was ignored.
    const stages = [
      'Curating replacement tracks…',
      'Resolving tracks with Spotify…',
      'Building revised playlist…',
    ];
    let stageIndex = 0;
    stageTimer = window.setInterval(() => {
      if (inlineStatusText) inlineStatusText.textContent = stages[Math.min(stageIndex, stages.length - 1)];
      if (stageIndex < stages.length - 1) stageIndex += 1;
    }, 6000);

    try {
      const response = await fetch(`/api/history/${encodeURIComponent(id)}/refine`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({instruction}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Could not refine playlist.');
      if (inlineStatusText) inlineStatusText.textContent = 'Refinement complete. Reloading…';
      if (data.notice) window.alert(data.notice);
      window.location.reload();
    } catch (error) {
      if (stageTimer) window.clearInterval(stageTimer);
      form.classList.remove('is-working');
      button.disabled = false;
      button.textContent = originalButtonText;
      if (inlineStatus) inlineStatus.hidden = true;
      if (terminal) terminal.dataset.active = 'false';
      if (status) status.textContent = error.message;
      else window.alert(error.message);
    }
  }

  async function deleteOne(button) {
    const id = button.dataset.id;
    const article = button.closest('.playlist');
    const name = article?.querySelector('h3')?.textContent?.trim() || 'this playlist';
    if (!id || !article) return;
    if (!window.confirm(`Remove “${name}” from Tune Raider history?\n\nThis will not delete the Spotify playlist.`)) return;

    button.disabled = true;
    try {
      const response = await fetch(`/api/history/${encodeURIComponent(id)}`, {method:'DELETE'});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Could not remove playlist from history.');
      article.remove();
      syncCount();
    } catch (error) {
      button.disabled = false;
      window.alert(error.message);
    }
  }

  async function clearAll(button) {
    const history = document.querySelector('#history');
    if (!history) return;
    const total = history.querySelectorAll('.playlist').length;
    if (!total) return;
    if (!window.confirm(`Clear all ${total} playlists from Tune Raider history?\n\nThis will not delete any Spotify playlists.`)) return;

    button.disabled = true;
    try {
      const response = await fetch('/api/history', {method:'DELETE'});
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Could not clear playlist history.');
      history.innerHTML = EMPTY_HISTORY;
      syncCount();
    } catch (error) {
      button.disabled = false;
      window.alert(error.message);
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    injectStyles();
    enhanceHistory();

    const status = document.querySelector('#status');
    if (status) {
      const appendBuildNotice = () => {
        const text = status.textContent.trim();
        if (pendingBuildNotice && text.startsWith('Built “')) {
          const notice = pendingBuildNotice;
          pendingBuildNotice = '';
          status.textContent = `${text} ${notice}`;
        }
      };
      new MutationObserver(appendBuildNotice).observe(status, {childList:true, characterData:true, subtree:true});
    }

    const history = document.querySelector('#history');
    if (history) new MutationObserver(enhanceHistory).observe(history, {childList:true, subtree:true});

    document.addEventListener('click', event => {
      const refineButton = event.target.closest('.history-refine');
      if (refineButton) {
        event.preventDefault();
        toggleRefine(refineButton);
        return;
      }
      const applyButton = event.target.closest('.history-refine-apply');
      if (applyButton) {
        event.preventDefault();
        applyRefinement(applyButton);
        return;
      }
      const cancelButton = event.target.closest('.history-refine-cancel');
      if (cancelButton) {
        event.preventDefault();
        const form = cancelButton.closest('.history-refine-form');
        if (form) form.hidden = true;
        return;
      }
      const removeButton = event.target.closest('.history-remove');
      if (removeButton) {
        event.preventDefault();
        deleteOne(removeButton);
        return;
      }
      const clearButton = event.target.closest('.history-clear');
      if (clearButton) {
        event.preventDefault();
        clearAll(clearButton);
      }
    });
  });
})();
