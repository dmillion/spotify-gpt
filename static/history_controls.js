(() => {
  const EMPTY_HISTORY = '<div class="empty">No playlists yet. Give the machine a mood.</div>';

  function injectStyles() {
    if (document.querySelector('#history-controls-style')) return;
    const style = document.createElement('style');
    style.id = 'history-controls-style';
    style.textContent = `
      .history-head-actions { display:flex; align-items:center; gap:12px; }
      .history-clear,
      .history-remove {
        min-height:36px;
        padding:7px 10px;
        border:1px solid var(--line-strong);
        background:transparent;
        color:var(--muted);
        font:500 11px/1.4 'DM Mono',monospace;
        text-transform:uppercase;
        letter-spacing:.04em;
      }
      .history-clear:hover,
      .history-remove:hover {
        color:var(--red);
        border-color:var(--red);
        background:color-mix(in srgb,var(--red) 8%,transparent);
      }
      .history-clear[hidden] { display:none; }
      @media (max-width:700px) {
        .history-head-actions { gap:8px; }
        .history-clear,
        .history-remove { min-height:40px; }
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
      if (!actions || !regen || actions.querySelector('.history-remove')) return;

      const removeButton = document.createElement('button');
      removeButton.type = 'button';
      removeButton.className = 'history-remove';
      removeButton.dataset.id = regen.dataset.id || '';
      removeButton.textContent = 'Remove';
      removeButton.title = 'Remove from Tune Raider history only';
      actions.appendChild(removeButton);
    });

    syncCount();
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

    const history = document.querySelector('#history');
    if (history) new MutationObserver(enhanceHistory).observe(history, {childList:true, subtree:true});

    document.addEventListener('click', event => {
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
