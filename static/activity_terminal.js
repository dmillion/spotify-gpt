(() => {
  let cursor = 0;
  let primed = false;
  let timer = null;

  if (!document.querySelector('script[data-tune-raider-usage]')) {
    const usageScript = document.createElement('script');
    usageScript.src = '/static/usage_display.js';
    usageScript.dataset.tuneRaiderUsage = 'true';
    document.head.appendChild(usageScript);
  }

  function installStyles() {
    if (document.querySelector('#activity-terminal-styles')) return;
    const style = document.createElement('style');
    style.id = 'activity-terminal-styles';
    style.textContent = `
      .network-terminal-live {
        display:none;
        max-height:150px;
        overflow:hidden;
        margin:0;
        padding:0;
      }
      .network-terminal-live[data-has-lines='true'] { display:block; }
      .network-terminal-log {
        min-height:19px;
        color:var(--ink);
        overflow-wrap:anywhere;
      }
      .network-terminal-log + .network-terminal-log { margin-top:2px; }
      .network-terminal-log::before { content:'> '; color:var(--acid); }
      .network-terminal[data-live='true'] .network-terminal-line,
      .network-terminal[data-live='true'] .network-terminal-note { display:none; }
    `;
    document.head.appendChild(style);
  }

  function ensureLiveArea() {
    const terminal = document.querySelector('.network-terminal');
    const body = terminal?.querySelector('.network-terminal-body');
    if (!terminal || !body) return null;
    let live = body.querySelector('.network-terminal-live');
    if (!live) {
      live = document.createElement('div');
      live.className = 'network-terminal-live';
      body.insertBefore(live, body.querySelector('.network-terminal-track'));
    }
    return {terminal, live};
  }

  function resetLive(terminal, live) {
    terminal.dataset.live = 'false';
    live.dataset.hasLines = 'false';
    live.replaceChildren();
  }

  function appendLines(lines) {
    const nodes = ensureLiveArea();
    if (!nodes || !Array.isArray(lines) || !lines.length) return;
    const {terminal, live} = nodes;
    if (terminal.dataset.active !== 'true') return;

    terminal.dataset.live = 'true';
    live.dataset.hasLines = 'true';
    for (const entry of lines) {
      const line = document.createElement('div');
      line.className = 'network-terminal-log';
      line.textContent = String(entry?.message || '');
      live.appendChild(line);
    }
    while (live.children.length > 7) live.firstElementChild?.remove();
  }

  async function poll() {
    try {
      const response = await fetch(`/static/activity.json?ts=${Date.now()}`, {cache:'no-store'});
      if (!response.ok) return;
      const data = await response.json();
      const latest = Number(data.cursor) || 0;
      const lines = Array.isArray(data.lines) ? data.lines : [];
      if (!primed) {
        cursor = latest;
        primed = true;
        return;
      }
      const fresh = lines.filter(entry => Number(entry?.id) > cursor);
      cursor = Math.max(cursor, latest);
      appendLines(fresh);
    } catch (_) {
      // Keep the faux terminal activity if the diagnostic feed is unavailable.
    }
  }

  function install() {
    if (timer) return;
    installStyles();
    const nodes = ensureLiveArea();
    if (!nodes) {
      setTimeout(install, 100);
      return;
    }
    const {terminal, live} = nodes;
    new MutationObserver(() => {
      if (terminal.dataset.active !== 'true') resetLive(terminal, live);
    }).observe(terminal, {attributes:true, attributeFilter:['data-active']});
    poll();
    timer = setInterval(poll, 500);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install);
  else install();
  window.addEventListener('beforeunload', () => { if (timer) clearInterval(timer); });
})();