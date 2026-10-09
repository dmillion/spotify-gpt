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

  const ACTIVE_KEY = 'tune-raider-active-add-to';
  const STAGE_LABELS = {
    queued: 'QUEUED', spotify_sync: 'READING SPOTIFY PLAYLIST',
    discovery: 'DISCOVERING CANDIDATES', resolution: 'RESOLVING SPOTIFY TRACKS',
    refill: 'SEARCHING FOR MORE CANDIDATES',
    duplicate_check: 'CHECKING FOR DUPLICATES',
    spotify_write: 'WRITING TRACKS TO SPOTIFY',
    history_save: 'UPDATING LOCAL HISTORY',
    complete: 'COMPLETE', interrupted: 'INTERRUPTED',
  };
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

  function saveActive(job) {
    try { localStorage.setItem(ACTIVE_KEY, JSON.stringify(job)); } catch (_) {}
  }
  function clearActive(jobId) {
    try {
      const active = JSON.parse(localStorage.getItem(ACTIVE_KEY) || 'null');
      if (!jobId || active?.jobId === jobId) localStorage.removeItem(ACTIVE_KEY);
    } catch (_) {}
  }
  function setButton(id, busy) {
    document.querySelectorAll('.history-add-to').forEach(button => {
      if (button.dataset.id !== String(id)) return;
      button.disabled = busy;
      button.textContent = busy ? 'Adding…' : 'Add to';
    });
  }
  let watching = null;

  async function watch(job) {
    if (watching === job.jobId) return;
    watching = job.jobId;
    saveActive(job);
    setButton(job.playlistId, true);
    const status = document.querySelector('#status');
    let failures = 0;
    try {
      while (true) {
        let state;
        try {
          const response = await fetch('/api/add-to-status/' + encodeURIComponent(job.jobId), {cache:'no-store'});
          if (!response.ok) throw new Error('Status HTTP ' + response.status);
          state = await response.json();
          failures = 0;
        } catch (error) {
          failures++;
          if (status) status.textContent = 'ADD TO / CONNECTION INTERRUPTED — RETRYING STATUS CHECK (' + failures + ')';
          if (failures >= 30) {
            window.TuneRaiderProgress?.stopServerProgress(false, 'STATUS UNAVAILABLE');
            reportFailure({operation:'Add to playlist', jobId:job.jobId, message:'Could not reach the job status endpoint. The server may still be working. Refresh to resume status checks.', detail:String(error)});
            return;
          }
          await sleep(3000);
          continue;
        }
        window.TuneRaiderProgress?.setServerProgress(state.stage, state.progress);
        if (status) status.textContent = 'ADD TO / ' + (STAGE_LABELS[state.stage] || state.stage).toUpperCase()
          + ' · ' + state.progress + '% · JOB ' + job.jobId.slice(0, 8);
        if (state.status === 'complete') {
          clearActive(job.jobId);
          window.TuneRaiderProgress?.stopServerProgress(true, 'TRACKS ADDED');
          if (status) status.textContent = 'ADD TO COMPLETE / ' + (state.result?.added ?? 0) + ' TRACKS ADDED';
          if (state.result?.notice) window.alert(state.result.notice);
          // Refresh history without discarding the completion message.
          try {
            const refresh = document.querySelector('#machine-status-refresh');
            if (refresh) refresh.click();
          } catch (_) {}
          window.location.reload();
          return;
        }
        if (state.status === 'failed' || state.status === 'missing') {
          clearActive(job.jobId);
          window.TuneRaiderProgress?.stopServerProgress(false, 'ADD TO FAILED');
          reportFailure({
            operation:'Add to playlist', jobId:job.jobId, playlistId:job.playlistId,
            stage:state.stage, progress:state.progress, message:state.error || 'Job not found',
            timestamp:state.updated_at,
            guidance:state.stage === 'spotify_write' || state.stage === 'history_save' || state.stage === 'interrupted'
              ? 'Spotify may have received tracks. Check the playlist before retrying.'
              : 'Check the server activity log for the underlying exception.',
          });
          return;
        }
        await sleep(2000);
      }
    } finally {
      watching = null;
      setButton(job.playlistId, false);
    }
  }

  async function addMore(button) {
    const id = button.dataset.id;
    if (!id || button.disabled || watching) return;
    button.disabled = true;
    const status = document.querySelector('#status');
    document.querySelector('#add-to-error-details')?.remove();
    if (status) status.textContent = 'SUBMITTING ADD TO JOB...';
    const requestId = 'add-' + Date.now() + '-' + Math.random().toString(36).slice(2);
    try {
      const response = await fetch('/api/history/' + encodeURIComponent(id) + '/add', {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({request_id:requestId}),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || 'Add to submission failed (HTTP ' + response.status + ')');
      if (!data.job_id) throw new Error('Server did not return a job ID.');
      await watch({jobId:data.job_id, playlistId:id});
    } catch (error) {
      reportFailure({operation:'Add to playlist', playlistId:id, message:String(error?.message || error)});
    } finally {
      button.disabled = false;
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
    try {
      const job = JSON.parse(localStorage.getItem(ACTIVE_KEY) || 'null');
      if (job?.jobId && job?.playlistId) watch(job);
    } catch (_) {}
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
