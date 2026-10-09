(() => {
  const TASKS = {
    generate: {
      status: 'GENERATING NEW PLAYLIST',
      stages: [
        ['INTERPRETING PROMPT'],
        ['BUILDING SOUND PROFILE'],
        ['SEARCHING DISCOVERY SOURCES'],
        ['CURATING CANDIDATES'],
        ['RESOLVING WITH SPOTIFY'],
        ['BUILDING PLAYLIST'],
      ],
    },
    regenerate: {
      status: 'REGENERATING FROM ORIGINAL PROMPT',
      stages: [
        ['RESETTING THE SEARCH'],
        ['REBUILDING SOUND PROFILE'],
        ['SEARCHING FRESH CANDIDATES'],
        ['CURATING A NEW DRAW'],
        ['RESOLVING WITH SPOTIFY'],
        ['BUILDING ALTERNATE PLAYLIST'],
      ],
    },
    refine: {
      status: 'REFINING CURRENT PLAYLIST',
      stages: [
        ['READING LIVE SPOTIFY STATE'],
        ['COMPARING CHANGES'],
        ['PLANNING THE ITERATION'],
        ['DISCOVERING REPLACEMENTS'],
        ['CURATING THE REVISION'],
        ['RESOLVING WITH SPOTIFY'],
        ['BUILDING REVISED PLAYLIST'],
      ],
    },
    add: {
      status: 'EXPANDING CURRENT PLAYLIST',
      stages: [
        ['READING LIVE SPOTIFY STATE'],
        ['LEARNING THE CURRENT SHAPE'],
        ['HONORING MANUAL TRIMS'],
        ['SEARCHING FOR MORE'],
        ['CURATING ADDITIONS'],
        ['RESOLVING WITH SPOTIFY'],
        ['APPENDING TRACKS'],
      ],
    },
  };

  let activeToken = 0;
  let activeType = null;
  let activeController = null;
  let activeRequest = false;
  let stageTimer = null;
  let elapsedTimer = null;
  let startedAt = 0;
  let serverProgressActive = false;

  function runElapsedTimer(panel) {
    if (!startedAt) startedAt = Date.now();
    if (elapsedTimer) window.clearInterval(elapsedTimer);
    const update = () => {
      panel.querySelector('.task-progress-elapsed').textContent = formatElapsed(Date.now() - startedAt);
    };
    update();
    elapsedTimer = window.setInterval(update, 1000);
  }

  function classify(url, options = {}) {
    const method = String(options.method || 'GET').toUpperCase();
    if (method !== 'POST') return null;
    if (/\/api\/generate(?:\?|$)/.test(url)) return 'generate';
    if (/\/api\/history\/\d+\/regenerate(?:\?|$)/.test(url)) return 'regenerate';
    if (/\/api\/history\/\d+\/refine(?:\?|$)/.test(url)) return 'refine';
    if (/\/api\/history\/\d+\/add(?:\?|$)/.test(url)) return 'add';
    return null;
  }

  function actionTypeFromClick(target) {
    if (target.closest('#generate')) return 'generate';
    if (target.closest('.regen')) return 'regenerate';
    if (target.closest('.history-refine-apply')) return 'refine';
    if (target.closest('.history-add-to')) return 'add';
    return null;
  }

  function taskLabel(type) {
    return ({
      generate: 'new playlist',
      regenerate: 'regeneration',
      refine: 'refinement',
      add: 'playlist expansion',
    })[type] || 'playlist task';
  }

  function installStyles() {
    if (document.querySelector('#task-progress-style')) return;
    const style = document.createElement('style');
    style.id = 'task-progress-style';
    style.textContent = `
      .task-progress {
        display:none;
        margin:-10px 0 32px;
        padding:10px 0 0;
      }
      .task-progress.is-active,
      .task-progress.is-complete,
      .task-progress.is-error { display:block; }
      .task-progress-stage {
        display:grid;
        grid-template-columns:minmax(0,1fr) auto;
        gap:16px;
        align-items:center;
      }
      .task-progress-stage-main {
        display:grid;
        gap:6px;
        min-width:0;
        justify-items:start;
      }
      .task-progress-stage-name {
        color:var(--warm-accent,var(--red));
        font:500 12px/1.4 'DM Mono',monospace;
        letter-spacing:.055em;
        overflow-wrap:anywhere;
      }
      .task-progress-elapsed {
        min-width:54px;
        text-align:right;
        color:var(--muted);
        font:500 11px 'DM Mono',monospace;
      }
      .task-progress-bar {
        position:relative;
        width:min(360px,100%);
        height:7px;
        overflow:hidden;
        border:1px solid color-mix(in srgb,var(--line-strong) 62%,transparent);
        background:color-mix(in srgb,var(--control) 72%,transparent);
      }
      .task-progress-bar-fill {
        display:block;
        width:0%;
        height:100%;
        background:var(--acid);
        box-shadow:0 0 8px var(--crt-glow);
        transition:width .55s ease-out;
      }
      /* Moving scanner shows the worker is busy even when stage progress holds steady. */
      .task-progress.is-active .task-progress-bar::after {
        content:'';
        position:absolute;
        inset:0;
        width:38%;
        background:linear-gradient(90deg,transparent, var(--acid), transparent);
        opacity:.75;
        transform:translateX(-110%);
        animation:task-progress-scan 1.65s linear infinite;
        pointer-events:none;
      }
      @keyframes task-progress-scan {
        from { transform:translateX(-110%); }
        to { transform:translateX(280%); }
      }
      .task-progress-percent { color:var(--muted); font:500 10px/1.3 'DM Mono',monospace; letter-spacing:.05em; }
      .task-progress-wave {
        display:flex;
        align-items:center;
        justify-content:center;
        gap:4px;
        width:104px;
        height:20px;
        overflow:hidden;
        border:1px solid color-mix(in srgb,var(--line-strong) 62%,transparent);
        background:color-mix(in srgb,var(--control) 72%,transparent);
        opacity:.78;
      }
      .task-progress-wave > span {
        width:4px;
        height:5px;
        border-radius:999px;
        background:var(--acid);
        opacity:.28;
        transform:scaleY(.7);
        transform-origin:center;
      }
      .is-active .task-progress-wave > span {
        animation:task-wave 1.25s ease-in-out infinite;
      }
      .is-active .task-progress-wave > span:nth-child(2) { animation-delay:.09s; }
      .is-active .task-progress-wave > span:nth-child(3) { animation-delay:.18s; }
      .is-active .task-progress-wave > span:nth-child(4) { animation-delay:.27s; }
      .is-active .task-progress-wave > span:nth-child(5) { animation-delay:.36s; }
      .is-active .task-progress-wave > span:nth-child(6) { animation-delay:.45s; }
      .is-active .task-progress-wave > span:nth-child(7) { animation-delay:.54s; }
      .is-active .task-progress-wave > span:nth-child(8) { animation-delay:.63s; }
      @keyframes task-wave {
        0%,100% {
          height:5px;
          opacity:.3;
          transform:scaleY(.8);
        }
        50% {
          height:16px;
          opacity:1;
          transform:scaleY(1);
        }
      }
      .task-progress.is-error .task-progress-stage-name { color:var(--red); }
      @media (max-width:700px) {
        .task-progress { margin-top:-6px; }
        .task-progress-stage { grid-template-columns:minmax(0,1fr) auto; gap:5px 12px; }
        .task-progress-stage-main { gap:6px; }
        .task-progress-wave { width:104px; }
      }
      /* Keep task feedback animated even when the device requests reduced motion.
         Tune Raider's long-running operations need an unmistakable busy state. */
    `;
    document.head.appendChild(style);
  }

  function ensurePanel() {
    installStyles();
    let panel = document.querySelector('#task-progress');
    if (panel) return panel;
    panel = document.createElement('section');
    panel.id = 'task-progress';
    panel.className = 'task-progress';
    panel.setAttribute('role', 'status');
    panel.setAttribute('aria-live', 'polite');
    panel.innerHTML = `
      <div class="task-progress-stage">
        <div class="task-progress-stage-main">
          <div class="task-progress-stage-name"></div>
          <div class="task-progress-bar" aria-hidden="true"><span class="task-progress-bar-fill"></span></div>
          <div class="task-progress-percent">0% · SERVER WORKER ACTIVE</div>
          <div class="task-progress-wave" aria-hidden="true">
            <span></span><span></span><span></span><span></span>
            <span></span><span></span><span></span><span></span>
          </div>
        </div>
        <div class="task-progress-elapsed">0:00</div>
      </div>
    `;
    const status = document.querySelector('#status');
    if (status?.parentNode) status.insertAdjacentElement('afterend', panel);
    else document.querySelector('.compose-column')?.appendChild(panel);
    return panel;
  }

  function setStage(panel, task, index) {
    const safeIndex = Math.min(index, task.stages.length - 1);
    panel.querySelector('.task-progress-stage-name').textContent = task.stages[safeIndex][0];
  }

  function setServerProgress(stage, progress, queuePosition=null) {
    const panel = ensurePanel();
    const value = Math.max(0, Math.min(100, Number(progress) || 0));
    const labels = {queued:'QUEUED ON TUNE RAIDER',curation:'CURATING / DISCOVERING CANDIDATES',spotify_auth:'AUTHORIZING SPOTIFY',spotify_resolution:'RESOLVING TRACKS WITH SPOTIFY',spotify_create:'CREATING SPOTIFY PLAYLIST',spotify_write:'WRITING TRACKS TO SPOTIFY',history_save:'SAVING TUNE RAIDER HISTORY',spotify_sync:'READING CURRENT SPOTIFY PLAYLIST',discovery:'DISCOVERING NEW TRACKS',resolution:'RESOLVING TRACKS WITH SPOTIFY',refill:'SEARCHING FOR MORE TRACKS',duplicate_check:'CHECKING FOR DUPLICATES',complete:'COMPLETE'};
    panel.className = value >= 100 ? 'task-progress is-complete' : 'task-progress is-active';
    if (value < 100) {
      serverProgressActive = true;
      if (!elapsedTimer) runElapsedTimer(panel);
    } else {
      serverProgressActive = false;
      if (elapsedTimer) window.clearInterval(elapsedTimer);
      elapsedTimer = null;
    }
    panel.querySelector('.task-progress-stage-name').textContent = labels[stage] || String(stage || 'SERVER WORKER ACTIVE').toUpperCase();
    panel.querySelector('.task-progress-bar-fill').style.width = value + '%';
    panel.querySelector('.task-progress-wave').style.opacity = stage === 'queued' ? '.25' : '.78';
    panel.querySelector('.task-progress-percent').textContent = stage === 'queued'
      ? (queuePosition ? 'QUEUE POSITION ' + queuePosition + ' · WAITING' : 'WAITING FOR SERVER WORKER')
      : value + '% · ' + (value >= 100 ? 'COMPLETE' : 'SERVER WORKER ACTIVE');
  }

  function stopServerProgress(ok=false, message='') {
    serverProgressActive = false;
    if (elapsedTimer) window.clearInterval(elapsedTimer);
    elapsedTimer = null;
    const panel = document.querySelector('#task-progress');
    if (!panel) return;
    panel.className = `task-progress ${ok ? 'is-complete' : 'is-error'}`;
    if (message) panel.querySelector('.task-progress-stage-name').textContent = message;
    if (ok) {
      panel.querySelector('.task-progress-bar-fill').style.width = '100%';
      panel.querySelector('.task-progress-percent').textContent = '100% · COMPLETE';
    }
  }

  function clearFinishedProgress() {
    if (activeRequest || serverProgressActive) return false;
    ++activeToken; // Invalidate any delayed completion callback.
    if (stageTimer) window.clearInterval(stageTimer);
    if (elapsedTimer) window.clearInterval(elapsedTimer);
    stageTimer = elapsedTimer = null;
    const panel = document.querySelector('#task-progress');
    if (panel) panel.className = 'task-progress';
    return true;
  }

  window.TuneRaiderProgress = {setServerProgress, stopServerProgress, clearFinishedProgress};

  function formatElapsed(ms) {
    const seconds = Math.max(0, Math.floor(ms / 1000));
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  }

  function scrollToProgress(panel) {
    window.requestAnimationFrame(() => {
      panel.scrollIntoView({behavior:'smooth', block:'start'});
    });
  }

  function startTask(type, controller) {
    const task = TASKS[type];
    if (!task) return 0;
    const panel = ensurePanel();
    const token = ++activeToken;
    if (stageTimer) window.clearInterval(stageTimer);
    if (elapsedTimer) window.clearInterval(elapsedTimer);
    startedAt = Date.now();
    serverProgressActive = false;
    activeType = type;
    activeController = controller;
    activeRequest = true;
    panel.className = 'task-progress is-active';
    panel.querySelector('.task-progress-elapsed').textContent = '0:00';
    panel.querySelector('.task-progress-bar-fill').style.width = '3%';
    panel.querySelector('.task-progress-percent').textContent = '3% · SUBMITTING';
    setStage(panel, task, 0);

    const legacyStatus = document.querySelector('#status');
    if (legacyStatus) legacyStatus.textContent = '';

    if (type === 'regenerate') scrollToProgress(panel);

    let stageIndex = 0;
    stageTimer = window.setInterval(() => {
      if (token !== activeToken) return;
      stageIndex = Math.min(stageIndex + 1, task.stages.length - 1);
      setStage(panel, task, stageIndex);
    }, 5200);
    runElapsedTimer(panel);
    return token;
  }

  function finishTask(token, ok, message = '', serverQueued = false) {
    if (!token || token !== activeToken) return;
    const panel = ensurePanel();
    if (stageTimer) window.clearInterval(stageTimer);
    if (elapsedTimer) window.clearInterval(elapsedTimer);
    stageTimer = elapsedTimer = null;
    activeRequest = false;
    activeType = null;
    activeController = null;
    serverProgressActive = serverQueued;
    panel.className = `task-progress ${serverQueued ? 'is-active' : (ok ? 'is-complete' : 'is-error')}`;
    panel.querySelector('.task-progress-stage-name').textContent = ok ? 'QUEUED ON SERVER' : (message || 'REQUEST FAILED');
    if (ok) {
      panel.querySelector('.task-progress-bar-fill').style.width = '5%';
      panel.querySelector('.task-progress-percent').textContent = '5% · SERVER WORKER ACTIVE';
    }
    panel.querySelector('.task-progress-elapsed').textContent = formatElapsed(Date.now() - startedAt);
    if (serverQueued) runElapsedTimer(panel);
    if (ok && !serverQueued) window.setTimeout(() => {
      if (token === activeToken) panel.className = 'task-progress';
    }, 2200);
  }

  // Ask before allowing a second long-running playlist action. Capture phase
  // prevents the underlying button handler from firing when the user says no.
  document.addEventListener('click', event => {
    const nextType = actionTypeFromClick(event.target);
    if (!nextType || !activeRequest) return;
    const current = taskLabel(activeType);
    const next = taskLabel(nextType);
    const replace = window.confirm(`A ${current} is still running. Stop it and start the ${next} instead?`);
    if (!replace) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }

    // Invalidate the old progress callbacks before aborting so their cleanup
    // cannot overwrite the replacement task's status.
    ++activeToken;
    activeRequest = false;
    activeType = null;
    if (stageTimer) window.clearInterval(stageTimer);
    if (elapsedTimer) window.clearInterval(elapsedTimer);
    stageTimer = elapsedTimer = null;
    activeController?.abort('Superseded by another Tune Raider task');
    activeController = null;
  }, true);

  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const url = String(args[0]?.url || args[0] || '');
    const options = {...(args[1] || {})};
    const type = classify(url, options);
    let controller = null;
    let token = 0;

    if (type) {
      controller = new AbortController();
      if (!options.signal) options.signal = controller.signal;
      args[1] = options;
      token = startTask(type, controller);
    }

    try {
      const response = await nativeFetch(...args);
      if (token) {
        if (response.ok) finishTask(token, true, '', response.status === 202 && (type === 'generate' || type === 'add'));
        else {
          let detail = `HTTP ${response.status}`;
          try {
            const body = await response.clone().json();
            if (body?.error) detail = body.error;
          } catch (_) {}
          finishTask(token, false, detail);
        }
      }
      return response;
    } catch (error) {
      if (token && token === activeToken) {
        if (error?.name === 'AbortError') {
          finishTask(token, false, 'STOPPED');
        } else if (error instanceof TypeError || /load failed|failed to fetch|network/i.test(String(error?.message || error))) {
          const panel = ensurePanel();
          if (stageTimer) window.clearInterval(stageTimer);
          if (elapsedTimer) window.clearInterval(elapsedTimer);
          stageTimer = elapsedTimer = null;
          activeRequest = false;
          activeType = null;
          activeController = null;
          panel.className = 'task-progress is-active';
          panel.querySelector('.task-progress-stage-name').textContent = 'CONNECTION INTERRUPTED — VERIFYING RESULT';
          panel.querySelector('.task-progress-elapsed').textContent = formatElapsed(Date.now() - startedAt);
          window.setTimeout(() => {
            if (token === activeToken) panel.className = 'task-progress';
          }, 3500);
        } else {
          finishTask(token, false, error?.message || String(error));
        }
      }
      throw error;
    }
  };

  const boot = () => ensurePanel();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
