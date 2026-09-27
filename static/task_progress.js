(() => {
  const TASKS = {
    generate: {
      status: 'GENERATING NEW PLAYLIST',
      stages: [
        ['INTERPRETING PROMPT', 'Mapping the artist, sound, mood, and constraints.'],
        ['BUILDING SOUND PROFILE', 'Connecting genre, tags, local reference data, and source-artist context.'],
        ['SEARCHING DISCOVERY SOURCES', 'Querying Last.fm, MusicBrainz, and the local specimen index.'],
        ['CURATING CANDIDATES', 'Ranking discoveries for fit, variety, energy, and source proximity.'],
        ['RESOLVING WITH SPOTIFY', 'Matching selected tracks to canonical Spotify releases.'],
        ['BUILDING PLAYLIST', 'Creating the playlist and saving the result.'],
      ],
    },
    regenerate: {
      status: 'REGENERATING FROM ORIGINAL PROMPT',
      stages: [
        ['RESETTING THE SEARCH', 'Starting a fresh discovery pass from the original prompt.'],
        ['REBUILDING SOUND PROFILE', 'Re-evaluating the source artist, genre, mood, and requested energy.'],
        ['SEARCHING FRESH CANDIDATES', 'Pulling another set from Last.fm, MusicBrainz, and local reference data.'],
        ['CURATING A NEW DRAW', 'Choosing a different set without treating the previous result as feedback.'],
        ['RESOLVING WITH SPOTIFY', 'Matching the new selections and replacing unresolved picks when possible.'],
        ['BUILDING ALTERNATE PLAYLIST', 'Creating a fresh playlist from the same prompt.'],
      ],
    },
    refine: {
      status: 'REFINING CURRENT PLAYLIST',
      stages: [
        ['READING LIVE SPOTIFY STATE', 'Scanning the playlist for manual additions and removals.'],
        ['COMPARING CHANGES', 'Keeping trimmed tracks out and treating surviving tracks as the current specimen set.'],
        ['PLANNING THE ITERATION', 'Applying your refinement instruction without losing the playlist identity.'],
        ['DISCOVERING REPLACEMENTS', 'Searching all discovery sources for tracks that fit the revised direction.'],
        ['CURATING THE REVISION', 'Preserving what works and selecting replacements or additions.'],
        ['RESOLVING WITH SPOTIFY', 'Matching the revised track list to Spotify.'],
        ['BUILDING REVISED PLAYLIST', 'Saving the new iterative version.'],
      ],
    },
    add: {
      status: 'EXPANDING CURRENT PLAYLIST',
      stages: [
        ['READING LIVE SPOTIFY STATE', 'Scanning the playlist before adding anything new.'],
        ['LEARNING THE CURRENT SHAPE', 'Using surviving and manually added tracks as positive specimens.'],
        ['HONORING MANUAL TRIMS', 'Keeping tracks you removed from immediately returning.'],
        ['SEARCHING FOR MORE', 'Querying Last.fm, MusicBrainz, and local reference data for adjacent discoveries.'],
        ['CURATING ADDITIONS', 'Choosing tracks that extend the playlist without diluting its sound.'],
        ['RESOLVING WITH SPOTIFY', 'Matching new selections to canonical Spotify tracks.'],
        ['APPENDING TRACKS', 'Adding the new tracks to the existing Spotify playlist.'],
      ],
    },
  };

  let activeToken = 0;
  let stageTimer = null;
  let elapsedTimer = null;
  let startedAt = 0;

  function classify(url, options = {}) {
    const method = String(options.method || 'GET').toUpperCase();
    if (method !== 'POST') return null;
    if (/\/api\/generate(?:\?|$)/.test(url)) return 'generate';
    if (/\/api\/history\/\d+\/regenerate(?:\?|$)/.test(url)) return 'regenerate';
    if (/\/api\/history\/\d+\/refine(?:\?|$)/.test(url)) return 'refine';
    if (/\/api\/history\/\d+\/add(?:\?|$)/.test(url)) return 'add';
    return null;
  }

  function installStyles() {
    if (document.querySelector('#task-progress-style')) return;
    const style = document.createElement('style');
    style.id = 'task-progress-style';
    style.textContent = `
      .task-progress {
        position:relative;
        display:none;
        overflow:hidden;
        margin:-10px 0 32px;
        padding:16px 20px 15px;
        border:1px solid color-mix(in srgb,var(--acid) 58%,var(--line-strong));
        border-left:3px solid var(--warm-accent,var(--red));
        background:linear-gradient(105deg,color-mix(in srgb,var(--accent-deeper,var(--control)) 86%,var(--control)),var(--surface));
        box-shadow:0 0 0 1px color-mix(in srgb,var(--acid) 6%,transparent),0 12px 32px rgba(0,0,0,.16);
        isolation:isolate;
      }
      .task-progress.is-active,
      .task-progress.is-complete,
      .task-progress.is-error { display:block; }
      .task-progress::before {
        content:'';
        position:absolute;
        inset:0;
        z-index:-1;
        opacity:.36;
        background:repeating-linear-gradient(0deg,transparent 0 5px,color-mix(in srgb,var(--acid) 6%,transparent) 6px 7px);
        pointer-events:none;
      }
      .task-progress.is-active::after {
        content:'';
        position:absolute;
        top:0;
        bottom:0;
        left:-28%;
        width:28%;
        background:linear-gradient(90deg,transparent,color-mix(in srgb,var(--acid) 12%,transparent),transparent);
        animation:task-scan 2.1s linear infinite;
        pointer-events:none;
      }
      @keyframes task-scan { to { transform:translateX(470%); } }
      .task-progress-stage {
        display:grid;
        grid-template-columns:minmax(210px,.62fr) minmax(0,1fr) auto;
        gap:16px;
        align-items:baseline;
      }
      .task-progress-stage-name {
        color:var(--acid);
        font:500 12px/1.4 'DM Mono',monospace;
        letter-spacing:.055em;
      }
      .task-progress-detail {
        color:var(--muted);
        font:13px/1.45 'Space Grotesk',sans-serif;
      }
      .task-progress-elapsed {
        min-width:54px;
        text-align:right;
        color:var(--muted);
        font:500 11px 'DM Mono',monospace;
      }
      .task-progress-rail {
        position:relative;
        height:5px;
        margin-top:15px;
        overflow:hidden;
        background:color-mix(in srgb,var(--line) 72%,transparent);
      }
      .task-progress-rail > span {
        position:absolute;
        inset:0 auto 0 0;
        width:22%;
        background:linear-gradient(90deg,var(--accent-deep,var(--acid)),var(--acid),var(--warm-accent,var(--red)));
        box-shadow:0 0 10px color-mix(in srgb,var(--acid) 50%,transparent);
      }
      .is-active .task-progress-rail > span { animation:task-runner 1.55s ease-in-out infinite alternate; }
      @keyframes task-runner { from { transform:translateX(-20%); } to { transform:translateX(365%); } }
      .task-progress.is-complete { border-left-color:var(--acid); }
      .task-progress.is-error { border-left-color:var(--red); }
      .task-progress.is-error .task-progress-stage-name { color:var(--red); }
      @media (max-width:700px) {
        .task-progress { margin-top:-6px; padding:14px; }
        .task-progress-stage { grid-template-columns:1fr auto; gap:5px 12px; }
        .task-progress-detail { grid-column:1 / -1; }
      }
      @media (prefers-reduced-motion:reduce) {
        .task-progress::after,.task-progress-rail > span { animation:none !important; }
      }
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
        <div class="task-progress-stage-name"></div>
        <div class="task-progress-detail"></div>
        <div class="task-progress-elapsed">0:00</div>
      </div>
      <div class="task-progress-rail" aria-hidden="true"><span></span></div>
    `;
    const status = document.querySelector('#status');
    if (status?.parentNode) status.insertAdjacentElement('afterend', panel);
    else document.querySelector('.compose-column')?.appendChild(panel);
    return panel;
  }

  function setStage(panel, task, index) {
    const stages = task.stages;
    const safeIndex = Math.min(index, stages.length - 1);
    const [name, detail] = stages[safeIndex];
    panel.querySelector('.task-progress-stage-name').textContent = name;
    panel.querySelector('.task-progress-detail').textContent = detail;
  }

  function formatElapsed(ms) {
    const seconds = Math.max(0, Math.floor(ms / 1000));
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
  }

  function startTask(type) {
    const task = TASKS[type];
    if (!task) return 0;
    const panel = ensurePanel();
    const token = ++activeToken;
    if (stageTimer) window.clearInterval(stageTimer);
    if (elapsedTimer) window.clearInterval(elapsedTimer);
    startedAt = Date.now();
    panel.className = 'task-progress is-active';
    panel.querySelector('.task-progress-elapsed').textContent = '0:00';
    setStage(panel, task, 0);

    const legacyStatus = document.querySelector('#status');
    if (legacyStatus) legacyStatus.textContent = task.status;

    let stageIndex = 0;
    stageTimer = window.setInterval(() => {
      if (token !== activeToken) return;
      stageIndex = Math.min(stageIndex + 1, task.stages.length - 1);
      setStage(panel, task, stageIndex);
    }, 5200);
    elapsedTimer = window.setInterval(() => {
      if (token !== activeToken) return;
      panel.querySelector('.task-progress-elapsed').textContent = formatElapsed(Date.now() - startedAt);
    }, 1000);
    return token;
  }

  function finishTask(token, ok, message = '') {
    if (!token || token !== activeToken) return;
    const panel = ensurePanel();
    if (stageTimer) window.clearInterval(stageTimer);
    if (elapsedTimer) window.clearInterval(elapsedTimer);
    stageTimer = elapsedTimer = null;
    panel.className = `task-progress ${ok ? 'is-complete' : 'is-error'}`;
    panel.querySelector('.task-progress-stage-name').textContent = ok ? 'COMPLETE' : 'REQUEST FAILED';
    panel.querySelector('.task-progress-detail').textContent = message || (ok ? 'Playlist operation complete.' : 'The operation did not complete.');
    panel.querySelector('.task-progress-elapsed').textContent = formatElapsed(Date.now() - startedAt);
    if (ok) window.setTimeout(() => {
      if (token === activeToken) panel.className = 'task-progress';
    }, 3200);
  }

  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const url = String(args[0]?.url || args[0] || '');
    const options = args[1] || {};
    const type = classify(url, options);
    const token = type ? startTask(type) : 0;
    try {
      const response = await nativeFetch(...args);
      if (token) {
        if (response.ok) finishTask(token, true);
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
      if (token) finishTask(token, false, error?.message || String(error));
      throw error;
    }
  };

  const boot = () => ensurePanel();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
