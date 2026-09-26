/* Apply theme/filter before first paint; switching never reloads or resets the playlist form. */
(() => {
  const key = 'bitraider-theme';
  const crtKey = 'bitraider-crt';
  const legacyKey = 'mixtape-foundry-theme';
  const themes = ['deep-space', 'amber'];
  const defaultPromptPlaceholder = 'Pick an artist or sound and describe where you want it to go...';
  let selected = 'deep-space';
  let crtEnabled = false;
  let lastIdeaArtist = '';
  let historyEnhanceInFlight = false;

  try {
    const saved = localStorage.getItem(key) || localStorage.getItem(legacyKey);
    if (themes.includes(saved)) selected = saved;
    crtEnabled = localStorage.getItem(crtKey) === 'on';
    localStorage.setItem(key, selected);
    localStorage.removeItem(legacyKey);
  } catch { /* Theme/filter switching still works when browser storage is unavailable. */ }
  document.documentElement.dataset.theme = selected;
  document.documentElement.dataset.crt = crtEnabled ? 'on' : 'off';

  const nativeSetInterval = window.setInterval.bind(window);
  window.setInterval = (callback, delay, ...args) => {
    if (delay === 9000) return 0;
    return nativeSetInterval(callback, delay, ...args);
  };

  const sample = items => items.length ? items[Math.floor(Math.random() * items.length)] : '';
  const loadingIcon = () => `
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2" opacity=".22"></circle>
      <path d="M12 3a9 9 0 0 1 9 9" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="square">
        <animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur=".8s" repeatCount="indefinite"></animateTransform>
      </path>
    </svg>`;

  function installNetworkTerminal(status) {
    if (!status || document.querySelector('.network-terminal')) return;

    if (!document.querySelector('#network-terminal-styles')) {
      const style = document.createElement('style');
      style.id = 'network-terminal-styles';
      style.textContent = `
        .network-terminal {
          display:none;
          margin:-6px 0 22px;
          border:1px solid var(--line);
          border-left:2px solid var(--acid);
          background:color-mix(in srgb,var(--control) 88%,transparent);
          box-shadow:inset 0 0 24px rgba(0,0,0,.22);
          color:var(--muted);
          font:12px/1.55 'DM Mono',monospace;
          overflow:hidden;
        }
        .network-terminal[data-active='true'] { display:block; }
        .network-terminal-head {
          display:flex;
          justify-content:space-between;
          gap:12px;
          padding:7px 10px;
          border-bottom:1px solid var(--line);
          color:var(--acid);
          letter-spacing:.08em;
          text-transform:uppercase;
        }
        .network-terminal-body { padding:10px; }
        .network-terminal-line { min-height:19px; color:var(--ink); }
        .network-terminal-prompt { color:var(--acid); }
        .network-terminal-note { margin-top:4px; color:var(--muted); opacity:.8; }
        .network-terminal-track {
          position:relative;
          height:3px;
          margin-top:10px;
          background:var(--line);
          overflow:hidden;
        }
        .network-terminal-track::after {
          content:'';
          position:absolute;
          top:0;
          bottom:0;
          width:24%;
          background:var(--acid);
          box-shadow:0 0 8px var(--crt-glow);
          animation:network-sweep 1.7s linear infinite;
        }
        .network-packets { display:flex; gap:5px; align-items:center; margin-top:9px; height:7px; }
        .network-packets span {
          width:4px;
          height:4px;
          background:var(--line-strong);
          opacity:.35;
          animation:network-packet 1.6s ease-in-out infinite;
        }
        .network-packets span:nth-child(2) { animation-delay:.12s; }
        .network-packets span:nth-child(3) { animation-delay:.24s; }
        .network-packets span:nth-child(4) { animation-delay:.36s; }
        .network-packets span:nth-child(5) { animation-delay:.48s; }
        .network-packets span:nth-child(6) { animation-delay:.60s; }
        .network-packets span:nth-child(7) { animation-delay:.72s; }
        .network-packets span:nth-child(8) { animation-delay:.84s; }
        .network-packets span:nth-child(9) { animation-delay:.96s; }
        .network-packets span:nth-child(10) { animation-delay:1.08s; }
        @keyframes network-sweep {
          from { transform:translateX(-110%); }
          to { transform:translateX(520%); }
        }
        @keyframes network-packet {
          0%,55%,100% { opacity:.25; transform:scaleY(.65); }
          25% { opacity:1; transform:scaleY(1.45); background:var(--acid); }
        }
        @media (prefers-reduced-motion:reduce) {
          .network-terminal-track::after,
          .network-packets span { animation:none; }
          .network-terminal-track::after { width:55%; opacity:.65; }
        }
      `;
      document.head.appendChild(style);
    }

    const terminal = document.createElement('div');
    terminal.className = 'network-terminal';
    terminal.setAttribute('aria-hidden', 'true');
    terminal.innerHTML = `
      <div class="network-terminal-head">
        <span>NET / OLLAMA</span>
        <span class="network-terminal-elapsed">00:00</span>
      </div>
      <div class="network-terminal-body">
        <div class="network-terminal-line"><span class="network-terminal-prompt">&gt;</span> <span class="network-terminal-message">request queued</span><span class="network-terminal-dots"></span></div>
        <div class="network-terminal-note">non-streaming inference / exact progress unavailable</div>
      </div>`;
    status.insertAdjacentElement('afterend', terminal);

    const elapsedNode = terminal.querySelector('.network-terminal-elapsed');
    const messageNode = terminal.querySelector('.network-terminal-message');
    const dotsNode = terminal.querySelector('.network-terminal-dots');
    const messages = [
      'request dispatched to Tune Raider',
      'waiting on Ollama structured response',
      'model inference still active',
      'holding connection open',
      'no token stream available; response pending',
      'still listening for model completion',
    ];
    let timer = null;
    let startedAt = 0;
    let tick = 0;

    const draw = () => {
      const elapsed = Math.max(0, Math.floor((Date.now() - startedAt) / 1000));
      const minutes = String(Math.floor(elapsed / 60)).padStart(2, '0');
      const seconds = String(elapsed % 60).padStart(2, '0');
      elapsedNode.textContent = `${minutes}:${seconds}`;
      const messageIndex = Math.min(messages.length - 1, Math.floor(elapsed / 12));
      messageNode.textContent = messages[messageIndex];
      dotsNode.textContent = '.'.repeat((tick % 3) + 1);
      tick += 1;
    };

    const start = () => {
      if (timer) return;
      startedAt = Date.now();
      tick = 0;
      terminal.dataset.active = 'true';
      draw();
      timer = nativeSetInterval(draw, 1000);
    };
    const stop = () => {
      if (timer) clearInterval(timer);
      timer = null;
      terminal.dataset.active = 'false';
    };
    const sync = () => {
      const text = status.textContent.trim();
      if (/^(CURATING|RESOLVING|GENERATING)\s*\//i.test(text)) start();
      else stop();
    };

    new MutationObserver(sync).observe(status, {childList:true, characterData:true, subtree:true});
    sync();
  }

  const broadOrCrossoverGenre = /^(rock|metal|alternative|alternative rock|indie|indie rock|experimental|crossover|fusion|rap rock|rap metal|funk metal|nu metal)$/i;
  const genreContexts = [
    {key:'sludge', pattern:/\b(sludge|sludge metal|doom|doom metal|stoner|stoner metal|stoner rock|desert rock|heavy psych|southern metal|drone metal)\b/i},
    {key:'black', pattern:/\b(black metal|post-black|atmospheric black metal|atmospheric black)\b/i},
    {key:'extreme', pattern:/\b(death metal|grindcore|grind|hardcore|hardcore punk|powerviolence|metalcore|mathcore)\b/i},
    {key:'punk', pattern:/\b(punk|post-punk|garage punk|garage rock|noise rock|post-hardcore)\b/i},
    {key:'shoegaze', pattern:/\b(shoegaze|dream pop|slowcore|ethereal wave|indie pop)\b/i},
    {key:'electronic', pattern:/\b(techno|house|electronic|idm|electro|drum and bass|dnb|breakbeat|synthwave)\b/i},
    {key:'hiphop', pattern:/\b(hip hop|hip-hop|boom bap|trap|abstract hip hop|underground hip hop)\b/i},
    {key:'country', pattern:/\b(country|americana|folk|bluegrass|alt-country)\b/i},
    {key:'jazz', pattern:/\b(jazz|bebop|soul jazz|spiritual jazz|jazz fusion)\b/i},
    {key:'ambient', pattern:/\b(ambient|dark ambient|drone|new age|soundscape|neoclassical|meditation)\b/i},
  ];

  function genreEvidence(artist) {
    const evidence = new Map();
    const genres = Array.isArray(artist.genres) ? artist.genres : [];
    genres.forEach((value, index) => {
      const name = String(value || '').trim();
      if (!name) return;
      const id = name.toLowerCase();
      const score = 2.4 - Math.min(index, 5) * .18;
      if (!evidence.has(id) || evidence.get(id).weight < score) evidence.set(id, {name, weight:score});
    });

    const tags = Array.isArray(artist.tags) ? artist.tags : [];
    tags.forEach((tag, index) => {
      const name = String(tag?.name || '').trim();
      if (!name) return;
      const rawWeight = Number(tag?.weight);
      const score = Number.isFinite(rawWeight) ? Math.max(.5, Math.min(4, rawWeight / 25)) : Math.max(.7, 1.5 - index * .12);
      const id = name.toLowerCase();
      if (!evidence.has(id) || evidence.get(id).weight < score) evidence.set(id, {name, weight:score});
    });
    return Array.from(evidence.values());
  }

  function dominantGenreContext(artist) {
    const evidence = genreEvidence(artist);
    const scored = genreContexts.map(context => {
      const matches = evidence.filter(item => !broadOrCrossoverGenre.test(item.name) && context.pattern.test(item.name));
      return {
        key: context.key,
        score: matches.reduce((total, item) => total + item.weight, 0),
        matches,
      };
    }).sort((a, b) => b.score - a.score);

    const winner = scored[0] || {key:'generic', score:0, matches:[]};
    const runnerUp = scored[1] || {score:0};
    const clearLead = winner.score >= 2.2 && (runnerUp.score === 0 || winner.score >= runnerUp.score * 1.35);
    const corroborated = winner.matches.length >= 2 || winner.score >= 3.2;

    if (!clearLead || !corroborated) {
      return {key:'generic', confident:false, genres:[]};
    }
    return {
      key:winner.key,
      confident:true,
      genres:winner.matches.sort((a, b) => b.weight - a.weight).map(item => item.name),
    };
  }

  function genreTheme(contextKey) {
    const theme = (scenes, qualities, constraints) => ({scenes, qualities, constraints});
    if (contextKey === 'sludge') return theme(
      ['a humid basement show', 'a desert highway after midnight', 'a blown-speaker practice room', 'a smoky bar near closing', 'a slow crawl through industrial backroads'],
      ['low-slung and riff-heavy', 'dirty, bass-heavy, and physical', 'fuzzy with real forward motion', 'massive without turning static', 'groove-first and rough-edged'],
      ['favor big riffs', 'avoid overly polished production', 'keep the low end huge', 'skip long shapeless intros', 'lean into deep cuts']
    );
    if (contextKey === 'black') return theme(
      ['a freezing predawn walk', 'a storm moving over empty fields', 'a blacked-out highway', 'a windswept ridge', 'a dim winter room'],
      ['cold, urgent, and atmospheric', 'raw but expansive', 'melodic without softening the edges', 'bleak with forward momentum', 'abrasive and cinematic'],
      ['avoid glossy production', 'keep the atmosphere tense', 'favor long arcs that still move', 'skip novelty picks', 'let melody emerge through the noise']
    );
    if (contextKey === 'extreme') return theme(
      ['a packed concrete room', 'a short violent commute', 'a fluorescent warehouse', 'a late-night gym session', 'a chaotic basement set'],
      ['percussive and relentless', 'dense but sharply rhythmic', 'fast with real groove underneath', 'ugly in a controlled way', 'compact, physical, and immediate'],
      ['keep dead air to a minimum', 'favor memorable breakdowns or rhythmic turns', 'avoid overlong intros', 'keep transitions aggressive', 'lean toward tracks with strong momentum']
    );
    if (contextKey === 'punk') return theme(
      ['a tiny club with bad lighting', 'a fast drive across town', 'a half-empty dive bar', 'a cramped practice space', 'a gray afternoon with too much caffeine'],
      ['raw and kinetic', 'angular with strong momentum', 'scrappy but hooky', 'noisy without losing the song', 'tense and rhythm-forward'],
      ['avoid slick production', 'keep the energy moving', 'favor memorable guitar or bass lines', 'skip filler', 'stay rough around the edges']
    );
    if (contextKey === 'shoegaze') return theme(
      ['a wet city drive after dark', 'a washed-out summer evening', 'a bedroom with the windows open', 'a gray Sunday afternoon', 'a train ride through rain'],
      ['hazy but melodic', 'soft-focus with strong hooks', 'washed-out and emotionally direct', 'dreamy without becoming weightless', 'warm, layered, and bittersweet'],
      ['keep the melodies strong', 'avoid abrupt stylistic jumps', 'favor texture over virtuosity', 'let the sequence gradually deepen', 'skip overly bright pop detours']
    );
    if (contextKey === 'electronic') return theme(
      ['a nearly empty club at 3 a.m.', 'a neon highway', 'a dark warehouse', 'a late-night coding session', 'a city train after midnight'],
      ['hypnotic and pulse-driven', 'textural with a strong rhythmic spine', 'mechanical but warm', 'propulsive without getting frantic', 'deep, repetitive, and immersive'],
      ['keep the transitions seamless', 'favor interesting production details', 'avoid cheesy festival peaks', 'let the groove evolve gradually', 'stay focused on rhythm and texture']
    );
    if (contextKey === 'hiphop') return theme(
      ['a night drive through the city', 'a dusty record-store afternoon', 'a low-key house party', 'a long train ride', 'a late summer evening'],
      ['rhythm-first and production-heavy', 'dusty and sample-rich', 'bass-forward with sharp drums', 'left-field but still head-nodding', 'moody with strong pocket'],
      ['favor distinctive beats', 'avoid generic radio picks', 'keep the sequencing rhythmic', 'lean into deep cuts', 'let production style guide the transitions']
    );
    if (contextKey === 'country') return theme(
      ['a two-lane road at dusk', 'a quiet bar after last call', 'a hot afternoon with the windows down', 'a long rural drive', 'a porch after a storm'],
      ['warm and lived-in', 'dusty with strong storytelling', 'melodic and unpolished', 'rootsy without getting sleepy', 'plainspoken with some grit'],
      ['avoid glossy crossover production', 'favor strong songwriting', 'lean into deep cuts', 'keep the pacing natural', 'let the instrumentation feel human']
    );
    if (contextKey === 'jazz') return theme(
      ['a dim room after midnight', 'a rainy afternoon', 'a quiet dinner that turns strange', 'a late train ride', 'a small club near closing'],
      ['loose but purposeful', 'warm, intricate, and rhythmic', 'improvisational without losing direction', 'smoky and harmonically rich', 'restless but controlled'],
      ['favor strong interplay', 'avoid background-music blandness', 'let the arrangements breathe', 'keep a rhythmic thread', 'mix familiar language with stranger turns']
    );
    if (contextKey === 'ambient') return theme(
      ['a sleepless 2 a.m. room', 'a slow sunrise', 'a long empty highway at night', 'a rain-muted window', 'a dark room with only streetlight coming in'],
      ['spacious and slow-moving', 'hazy and immersive', 'minimal but emotionally heavy', 'soft-edged and nocturnal', 'patient, textural, and low-lit'],
      ['avoid sudden energy spikes', 'let tracks breathe', 'favor long transitions', 'keep percussion restrained', 'stay immersive rather than dramatic']
    );
    return theme([], [], []);
  }

  function genericIdea(artist) {
    const ideas = [
      `Build a playlist around ${artist.name}'s sound; stay close to their musical neighborhood, favor deep cuts, and keep the transitions intentional.`,
      `Use ${artist.name} as the anchor and explore nearby artists without forcing a genre or mood shift; keep it cohesive and avoid stylistic detours.`,
      `Start from ${artist.name} and branch outward carefully; prioritize tracks that feel naturally related rather than chasing a specific scene or genre label.`,
    ];
    return sample(ideas);
  }

  function buildIdea(artist) {
    const context = dominantGenreContext(artist);
    if (!context.confident) return genericIdea(artist);

    const primaryGenre = context.genres[0] || '';
    const theme = genreTheme(context.key);
    const scene = sample(theme.scenes);
    const quality = sample(theme.qualities);
    const constraint = sample(theme.constraints);
    return Math.random() < 0.5
      ? `Start with ${artist.name}'s ${primaryGenre} side and build toward ${scene}; ${quality}, ${constraint}.`
      : `Build a ${primaryGenre} playlist around ${artist.name}: ${quality}; ${constraint}.`;
  }

  async function fetchIdeaProfiles() {
    const response = await fetch('/api/prompt-profile', {cache: 'no-store'});
    const profile = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(profile.error || 'Could not load playlist ideas.');
    const profiles = Array.isArray(profile.profiles)
      ? profile.profiles.filter(artist => artist?.name && Array.isArray(artist.genres) && artist.genres.length)
      : [];
    if (!profiles.length) throw new Error('No personalized playlist ideas are available yet.');
    return profiles;
  }

  async function enhanceHistoryTracks() {
    const history = document.querySelector('#history');
    const articles = history ? Array.from(history.querySelectorAll('.playlist')) : [];
    if (!articles.length || historyEnhanceInFlight) return;
    historyEnhanceInFlight = true;
    try {
      const response = await fetch('/api/history', {cache: 'no-store'});
      if (!response.ok) return;
      const items = await response.json();
      articles.forEach((article, index) => {
        const item = items[index];
        if (!item) return;
        article.dataset.regeneratePrompt = String(item.prompt || '');
        const tracks = article.querySelector('.tracks');
        if (!tracks || !Array.isArray(item.tracks) || item.tracks.length <= 12 || tracks.dataset.expandable === 'true') return;
        const marker = Array.from(tracks.querySelectorAll('.track')).find(element => /^\+\d+ more$/i.test(element.textContent.trim()));
        if (!marker) return;

        const remaining = item.tracks.slice(12);
        tracks.dataset.expandable = 'true';
        marker.setAttribute('role', 'button');
        marker.setAttribute('tabindex', '0');
        marker.setAttribute('aria-expanded', 'false');
        marker.setAttribute('aria-label', `Show ${remaining.length} more tracks`);

        const toggle = () => {
          const expanded = marker.getAttribute('aria-expanded') === 'true';
          if (expanded) {
            tracks.querySelectorAll('.track-extra').forEach(element => element.remove());
            marker.textContent = `+${remaining.length} more`;
            marker.setAttribute('aria-expanded', 'false');
            marker.setAttribute('aria-label', `Show ${remaining.length} more tracks`);
            return;
          }
          remaining.forEach(track => {
            const chip = document.createElement('span');
            chip.className = 'track track-extra';
            chip.textContent = `${track.artist} / ${track.title}`;
            tracks.insertBefore(chip, marker);
          });
          marker.textContent = 'Show less';
          marker.setAttribute('aria-expanded', 'true');
          marker.setAttribute('aria-label', 'Show fewer tracks');
        };

        marker.addEventListener('click', toggle);
        marker.addEventListener('keydown', event => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            toggle();
          }
        });
      });
    } catch (_) {
      // History remains usable even if expansion metadata cannot be refreshed.
    } finally {
      historyEnhanceInFlight = false;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    const picker = document.querySelector('#theme-select');
    const crtToggle = document.querySelector('#crt-toggle');
    const feedback = document.querySelector('#theme-feedback');

    const usageTitle = document.querySelector('#usage-title');
    if (usageTitle) usageTitle.textContent = 'Ollama usage';
    const usageNotes = document.querySelectorAll('.usage-details .usage-note');
    if (usageNotes.length > 1) {
      usageNotes[1].textContent = 'Tune Raider token counts reported by Ollama only. This meter does not represent your account-wide remaining free starter credits; check Ollama for that balance.';
    }
    const errorHelpLink = document.querySelector('#error-help-link');
    if (errorHelpLink) errorHelpLink.textContent = 'Open Ollama settings ↗';

    if (picker) {
      picker.value = selected;
      picker.addEventListener('change', () => {
        if (!themes.includes(picker.value)) return;
        document.documentElement.dataset.theme = picker.value;
        try {
          localStorage.setItem(key, picker.value);
          if (feedback) feedback.textContent = `${picker.selectedOptions[0].textContent} theme selected and saved.`;
        } catch {
          if (feedback) feedback.textContent = `${picker.selectedOptions[0].textContent} theme selected for this page. Your browser could not save the preference.`;
        }
      });
    }

    if (crtToggle) {
      crtToggle.checked = crtEnabled;
      crtToggle.addEventListener('change', () => {
        crtEnabled = crtToggle.checked;
        document.documentElement.dataset.crt = crtEnabled ? 'on' : 'off';
        try {
          localStorage.setItem(crtKey, crtEnabled ? 'on' : 'off');
          if (feedback) feedback.textContent = `CRT filter ${crtEnabled ? 'enabled' : 'disabled'} and saved.`;
        } catch {
          if (feedback) feedback.textContent = `CRT filter ${crtEnabled ? 'enabled' : 'disabled'} for this page.`;
        }
      });
    }

    window.addEventListener('storage', event => {
      if (event.key === key) {
        const theme = themes.includes(event.newValue) ? event.newValue : 'deep-space';
        document.documentElement.dataset.theme = theme;
        if (picker) picker.value = theme;
      }
      if (event.key === crtKey) {
        crtEnabled = event.newValue === 'on';
        document.documentElement.dataset.crt = crtEnabled ? 'on' : 'off';
        if (crtToggle) crtToggle.checked = crtEnabled;
      }
    });

    const promptBox = document.querySelector('#prompt');
    const composer = document.querySelector('.composer');
    const generateButton = document.querySelector('#generate');
    const status = document.querySelector('#status');
    const history = document.querySelector('#history');
    if (!promptBox || !composer || !generateButton) return;

    window.rotatePromptPlaceholder = () => {};
    promptBox.placeholder = defaultPromptPlaceholder;

    const actions = document.createElement('div');
    actions.className = 'composer-actions';
    composer.insertAdjacentElement('afterend', actions);
    actions.appendChild(generateButton);

    const ideaButton = document.createElement('button');
    ideaButton.type = 'button';
    ideaButton.className = 'idea-button';
    ideaButton.textContent = 'Tune It Up!';
    actions.insertBefore(ideaButton, generateButton);

    const clearButton = document.createElement('button');
    clearButton.type = 'button';
    clearButton.className = 'prompt-clear';
    clearButton.setAttribute('aria-label', 'Clear playlist prompt');
    clearButton.textContent = '×';
    composer.appendChild(clearButton);

    if (status) {
      const decorateStatus = () => {
        const text = status.textContent.trim();
        if (text.startsWith('CURATING /') && !status.querySelector('svg')) {
          status.innerHTML = `${loadingIcon()} <span>${text}</span>`;
        }
      };
      new MutationObserver(decorateStatus).observe(status, {childList: true, characterData: true, subtree: true});
      decorateStatus();
      installNetworkTerminal(status);
    }

    if (history) {
      history.addEventListener('click', event => {
        const regenerateButton = event.target.closest('.regen');
        if (!regenerateButton) return;
        const article = regenerateButton.closest('.playlist');
        const eyebrow = article?.querySelector('.eyebrow')?.textContent || '';
        const fallbackPrompt = eyebrow.replace(/^(Hybrid|MP3 library|Discovery) \/ /, '');
        const savedPrompt = article?.dataset.regeneratePrompt || fallbackPrompt;
        if (!savedPrompt) return;
        promptBox.value = savedPrompt;
        promptBox.dispatchEvent(new Event('input', {bubbles: true}));
      }, true);
      new MutationObserver(() => enhanceHistoryTracks()).observe(history, {childList: true});
      enhanceHistoryTracks();
    }

    ideaButton.addEventListener('click', async () => {
      ideaButton.disabled = true;
      ideaButton.innerHTML = `${loadingIcon()} <span>Fine Tuning…</span>`;
      try {
        const profiles = await fetchIdeaProfiles();
        const alternatives = profiles.filter(artist => artist.name !== lastIdeaArtist);
        const artist = sample(alternatives.length ? alternatives : profiles);
        lastIdeaArtist = artist.name;
        promptBox.value = buildIdea(artist);
        promptBox.dispatchEvent(new Event('input', {bubbles: true}));
        promptBox.focus();
      } catch (error) {
        if (status) status.textContent = error.message;
      } finally {
        ideaButton.textContent = 'Tune It Up!';
        ideaButton.disabled = false;
      }
    });

    clearButton.addEventListener('click', () => {
      promptBox.value = '';
      promptBox.dispatchEvent(new Event('input', {bubbles: true}));
      promptBox.focus();
    });
  });
})();
