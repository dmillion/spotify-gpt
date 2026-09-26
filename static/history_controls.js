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
      .history-head-actions { display:flex; align-items:center; gap:12px; }
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
      .history-refine:hover,
      .history-refine-apply:hover {
        color:var(--button-ink);
        border-color:var(--acid);
        background:var(--acid);
      }
      .history-clear:hover,
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
      .history-refine-form[hidden] { display:none; }
      .history-refine-form {
        grid-column:1 / -1;
        display:grid;
        grid-template-columns:minmax(0,1fr) auto auto;
        gap:8px;
        align-items:end;
        margin-top:4px;
        padding:12px;
        border-left:1px solid var(--line-strong);
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
      .history-refine-form.is-working { opacity:.65; pointer-events:none; }
      @media (max-width:700px) {
        .history-head-actions { gap:8px; }
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

    form.classList.add('is-working');
    const status = document.querySelector('#status');
    if (status) status.textContent = 'REFINING / CURATING / RESOLVING...';
    try {
      const response = await fetch(`/api/history/${encodeURIComponent(id)}/refine`, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({instruction}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Could not refine playlist.');
      if (data.notice) window.alert(data.notice);
      window.location.reload();
    } catch (error) {
      form.classList.remove('is-working');
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
