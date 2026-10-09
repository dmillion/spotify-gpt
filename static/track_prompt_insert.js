(() => {
  const prompt = document.querySelector('#prompt');
  if (!prompt || document.querySelector('#track-prompt-insert-style')) return;

  const style = document.createElement('style');
  style.id = 'track-prompt-insert-style';
  style.textContent = `
    .playlist .track {
      cursor:pointer;
      position:relative;
    }
    .playlist .track::after {
      content:'+';
      margin-left:7px;
      color:var(--warm-accent,var(--acid));
      opacity:0;
      transform:translateX(-3px);
      transition:opacity 120ms ease-out,transform 120ms ease-out;
    }
    .playlist .track:hover::after,
    .playlist .track:focus-visible::after {
      opacity:1;
      transform:translateX(0);
    }
    .playlist .track.track-prompt-added {
      border-color:var(--warm-accent,var(--acid)) !important;
      color:var(--history-text-strong,var(--ink)) !important;
      box-shadow:0 0 0 1px color-mix(in srgb,var(--warm-accent,var(--acid)) 24%,transparent);
    }
  `;
  document.head.appendChild(style);

  function isTrackReference(track) {
    const value = String(track.textContent || '').trim();
    return Boolean(value && value.includes(' / ') && !/^\+\d+\s+more$/i.test(value));
  }

  function trackReference(track) {
    if (!isTrackReference(track)) return '';

    const raw = String(track.textContent || '').replace(/\s+/g, ' ').trim();
    if (!raw) return '';

    // History chips are rendered as "Artist / Title". Use "Title by Artist"
    // because the backend already recognizes that as an explicit track anchor.
    const slash = raw.indexOf(' / ');
    if (slash > 0) {
      const artist = raw.slice(0, slash).trim();
      const title = raw.slice(slash + 3).trim();
      if (artist && title) return `${title} by ${artist}`;
    }

    // Graceful fallback if history rendering changes later.
    return raw;
  }

  function insertAtCursor(value) {
    const start = prompt.selectionStart ?? prompt.value.length;
    const end = prompt.selectionEnd ?? start;
    const before = prompt.value.slice(0, start);
    const after = prompt.value.slice(end);

    const hasExistingPrompt = prompt.value.trim().length > 0;
    const needsSeparator = hasExistingPrompt && before.trim().length > 0;
    const separator = needsSeparator ? ' + ' : '';
    const needsAfterSpace = after && !/^\s/.test(after);

    const insertion = `${separator}${value}${needsAfterSpace ? ' ' : ''}`;
    prompt.value = before.replace(/\s+$/, '') + insertion + after;
    const cursor = before.replace(/\s+$/, '').length + insertion.length;
    prompt.setSelectionRange(cursor, cursor);
    prompt.dispatchEvent(new Event('input', {bubbles:true}));
    prompt.focus();
  }

  function enhanceTracks() {
    document.querySelectorAll('.playlist .track').forEach(track => {
      if (!isTrackReference(track) || track.dataset.promptInsertReady === '1') return;
      track.dataset.promptInsertReady = '1';
      track.tabIndex = 0;
      track.setAttribute('role', 'button');
      track.title = 'Add this track as a reference in the prompt';
      track.setAttribute('aria-label', `Add ${String(track.textContent || '').trim()} to the prompt`);
    });
  }

  function addTrack(track) {
    const reference = trackReference(track);
    if (!reference) return;
    insertAtCursor(reference);
    track.classList.add('track-prompt-added');
    window.setTimeout(() => track.classList.remove('track-prompt-added'), 650);
  }

  document.addEventListener('click', event => {
    const track = event.target.closest('.playlist .track');
    if (!track || !isTrackReference(track)) return;
    event.preventDefault();
    addTrack(track);
  });

  document.addEventListener('keydown', event => {
    const track = event.target.closest?.('.playlist .track');
    if (!track || !isTrackReference(track) || (event.key !== 'Enter' && event.key !== ' ')) return;
    event.preventDefault();
    addTrack(track);
  });

  enhanceTracks();
  const history = document.querySelector('#history');
  if (history) new MutationObserver(enhanceTracks).observe(history, {childList:true, subtree:true});
})();
