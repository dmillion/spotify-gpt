(() => {
  const prompt = document.querySelector('#prompt');
  if (!prompt || document.querySelector('#playlist-mention-menu')) return;

  let playlists = [];
  let matches = [];
  let activeIndex = 0;
  let mentionStart = -1;

  const style = document.createElement('style');
  style.textContent = `
    .playlist-mention-help { margin:8px 0 0; color:var(--muted); font:500 10px/1.4 'DM Mono',monospace; letter-spacing:.03em; text-transform:uppercase; }
    .playlist-mention-help code { color:var(--accent-mid,var(--acid)); font:inherit; }
    .playlist-mention-menu { position:fixed; z-index:1000; display:none; width:min(540px,calc(100vw - 28px)); max-height:290px; overflow:auto; border:1px solid var(--line-strong); background:var(--surface); box-shadow:0 12px 35px rgba(0,0,0,.35); padding:5px; }
    .playlist-mention-menu.is-open { display:block; }
    .playlist-mention-item { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:5px 12px; width:100%; padding:10px 11px; border:0; background:transparent; color:var(--ink); text-align:left; font:500 12px/1.35 'DM Mono',monospace; }
    .playlist-mention-item:hover,.playlist-mention-item.is-active { background:color-mix(in srgb,var(--accent-deep,var(--acid)) 34%,var(--control)); color:var(--acid); }
    .playlist-mention-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .playlist-mention-count { color:var(--warm-accent,var(--muted)); white-space:nowrap; }
    .playlist-mention-desc { grid-column:1 / -1; color:var(--muted); font-size:10px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  `;
  document.head.appendChild(style);

  const menu = document.createElement('div');
  menu.id = 'playlist-mention-menu';
  menu.className = 'playlist-mention-menu';
  menu.setAttribute('role', 'listbox');
  document.body.appendChild(menu);

  const help = document.createElement('p');
  help.className = 'playlist-mention-help';
  help.innerHTML = 'Type <code>@</code> to reference one of your saved playlists in this prompt.';
  prompt.closest('.composer')?.insertAdjacentElement('afterend', help);

  function currentMention() {
    const cursor = prompt.selectionStart ?? prompt.value.length;
    const before = prompt.value.slice(0, cursor);
    const at = before.lastIndexOf('@');
    if (at < 0) return null;
    const fragment = before.slice(at + 1);
    if (/\n/.test(fragment) || fragment.includes(']') || fragment.length > 80) return null;
    const previous = at > 0 ? before[at - 1] : '';
    if (previous && /[\w.]/.test(previous)) return null;
    return {start: at, cursor, query: fragment.trim().toLowerCase()};
  }

  function positionMenu() {
    const rect = prompt.getBoundingClientRect();
    menu.style.left = `${Math.max(14, rect.left)}px`;
    menu.style.top = `${Math.min(window.innerHeight - 310, rect.bottom + 6)}px`;
    menu.style.width = `${Math.min(540, rect.width)}px`;
  }

  function render() {
    const mention = currentMention();
    if (!mention || !playlists.length) return close();
    mentionStart = mention.start;
    matches = playlists.filter(item => {
      if (!mention.query) return true;
      return `${item.name} ${item.description || ''}`.toLowerCase().includes(mention.query);
    }).slice(0, 10);
    if (!matches.length) return close();
    activeIndex = Math.min(activeIndex, matches.length - 1);
    menu.innerHTML = matches.map((item, index) => `
      <button type="button" class="playlist-mention-item${index === activeIndex ? ' is-active' : ''}" data-index="${index}" role="option" aria-selected="${index === activeIndex}">
        <span class="playlist-mention-name">${escapeHtml(item.name)}</span>
        <span class="playlist-mention-count">${item.track_count || 0} tracks</span>
        <span class="playlist-mention-desc">${escapeHtml(item.description || 'Saved Tune Raider playlist')}</span>
      </button>`).join('');
    positionMenu();
    menu.classList.add('is-open');
  }

  function close() {
    menu.classList.remove('is-open');
    menu.innerHTML = '';
    matches = [];
    activeIndex = 0;
    mentionStart = -1;
  }

  function escapeHtml(value) {
    return String(value || '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[char]));
  }

  function choose(index) {
    const item = matches[index];
    if (!item || mentionStart < 0) return;
    const cursor = prompt.selectionStart ?? prompt.value.length;
    const before = prompt.value.slice(0, mentionStart);
    const after = prompt.value.slice(cursor);
    const duplicates = playlists.filter(row => String(row.name).toLowerCase() === String(item.name).toLowerCase()).length;
    const token = duplicates > 1 ? `@[${item.name}](playlist:${item.id})` : `@[${item.name}]`;
    const spacer = after && !/^\s/.test(after) ? ' ' : '';
    prompt.value = `${before}${token}${spacer}${after}`;
    const next = before.length + token.length + spacer.length;
    prompt.setSelectionRange(next, next);
    prompt.dispatchEvent(new Event('input', {bubbles:true}));
    prompt.focus();
    close();
  }

  prompt.addEventListener('input', () => { activeIndex = 0; render(); });
  prompt.addEventListener('click', render);
  prompt.addEventListener('keydown', event => {
    if (!menu.classList.contains('is-open')) return;
    if (event.key === 'ArrowDown') { event.preventDefault(); activeIndex = (activeIndex + 1) % matches.length; render(); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); activeIndex = (activeIndex - 1 + matches.length) % matches.length; render(); }
    else if (event.key === 'Enter' || event.key === 'Tab') { event.preventDefault(); choose(activeIndex); }
    else if (event.key === 'Escape') { event.preventDefault(); close(); }
  });

  menu.addEventListener('mousedown', event => {
    const item = event.target.closest('.playlist-mention-item');
    if (!item) return;
    event.preventDefault();
    choose(Number(item.dataset.index || 0));
  });
  document.addEventListener('mousedown', event => { if (event.target !== prompt && !menu.contains(event.target)) close(); });
  window.addEventListener('resize', () => menu.classList.contains('is-open') && positionMenu());
  window.addEventListener('scroll', () => menu.classList.contains('is-open') && positionMenu(), true);

  fetch('/api/prompt-playlists')
    .then(response => response.ok ? response.json() : [])
    .then(data => { playlists = Array.isArray(data) ? data : []; })
    .catch(() => { playlists = []; });
})();
