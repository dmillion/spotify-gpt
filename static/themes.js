/* Apply theme/filter before first paint; switching never reloads or resets the playlist form. */
(() => {
  const key = 'bitraider-theme';
  const crtKey = 'bitraider-crt';
  const legacyKey = 'mixtape-foundry-theme';
  const themes = ['deep-space', 'amber'];
  const defaultPromptPlaceholder = 'Pick an artist or sound and describe where you want it to go...';
  let selected = 'deep-space';
  let crtEnabled = false;
  let ideaProfiles = [];
  let lastIdeaArtist = '';

  try {
    const saved = localStorage.getItem(key) || localStorage.getItem(legacyKey);
    if (themes.includes(saved)) selected = saved;
    crtEnabled = localStorage.getItem(crtKey) === 'on';
    localStorage.setItem(key, selected);
    localStorage.removeItem(legacyKey);
  } catch { /* Theme/filter switching still works when browser storage is unavailable. */ }
  document.documentElement.dataset.theme = selected;
  document.documentElement.dataset.crt = crtEnabled ? 'on' : 'off';

  // The legacy inline prompt code still schedules a 9-second placeholder rotation.
  // Suppress only that obsolete timer; usage polling continues normally.
  const nativeSetInterval = window.setInterval.bind(window);
  window.setInterval = (callback, delay, ...args) => {
    if (delay === 9000) return 0;
    return nativeSetInterval(callback, delay, ...args);
  };

  const sample = items => items.length ? items[Math.floor(Math.random() * items.length)] : '';

  function genreTheme(genres) {
    const text = genres.join(' ').toLowerCase();
    const theme = (scenes, qualities, constraints) => ({scenes, qualities, constraints});
    if (/(ambient|drone|new age|soundscape|neoclassical|meditation)/.test(text)) {
      return theme(
        ['a sleepless 2 a.m. room', 'a slow sunrise', 'a long empty highway at night', 'a rain-muted window', 'a dark room with only streetlight coming in'],
        ['spacious and slow-moving', 'hazy and immersive', 'minimal but emotionally heavy', 'soft-edged and nocturnal', 'patient, textural, and low-lit'],
        ['avoid sudden energy spikes', 'let tracks breathe', 'favor long transitions', 'keep percussion restrained', 'stay immersive rather than dramatic']
      );
    }
    if (/(sludge|doom|stoner|desert rock|heavy psych|southern metal)/.test(text)) {
      return theme(
        ['a humid basement show', 'a desert highway after midnight', 'a blown-speaker practice room', 'a smoky bar near closing', 'a slow crawl through industrial backroads'],
        ['low-slung and riff-heavy', 'dirty, bass-heavy, and physical', 'fuzzy with real forward motion', 'massive without turning static', 'groove-first and rough-edged'],
        ['favor big riffs', 'avoid overly polished production', 'keep the low end huge', 'skip long shapeless intros', 'lean into deep cuts']
      );
    }
    if (/(black metal|post-black|atmospheric black)/.test(text)) {
      return theme(
        ['a freezing predawn walk', 'a storm moving over empty fields', 'a blacked-out highway', 'a windswept ridge', 'a dim winter room'],
        ['cold, urgent, and atmospheric', 'raw but expansive', 'melodic without softening the edges', 'bleak with forward momentum', 'abrasive and cinematic'],
        ['avoid glossy production', 'keep the atmosphere tense', 'favor long arcs that still move', 'skip novelty picks', 'let melody emerge through the noise']
      );
    }
    if (/(death metal|grind|grindcore|hardcore|powerviolence|metalcore)/.test(text)) {
      return theme(
        ['a packed concrete room', 'a short violent commute', 'a fluorescent warehouse', 'a late-night gym session', 'a chaotic basement set'],
        ['percussive and relentless', 'dense but sharply rhythmic', 'fast with real groove underneath', 'ugly in a controlled way', 'compact, physical, and immediate'],
        ['keep dead air to a minimum', 'favor memorable breakdowns or rhythmic turns', 'avoid overlong intros', 'keep transitions aggressive', 'lean toward tracks with strong momentum']
      );
    }
    if (/(shoegaze|dream pop|slowcore|ethereal|indie pop)/.test(text)) {
      return theme(
        ['a wet city drive after dark', 'a washed-out summer evening', 'a bedroom with the windows open', 'a gray Sunday afternoon', 'a train ride through rain'],
        ['hazy but melodic', 'soft-focus with strong hooks', 'washed-out and emotionally direct', 'dreamy without becoming weightless', 'warm, layered, and bittersweet'],
        ['keep the melodies strong', 'avoid abrupt stylistic jumps', 'favor texture over virtuosity', 'let the sequence gradually deepen', 'skip overly bright pop detours']
      );
    }
    if (/(techno|house|electronic|idm|electro|dnb|drum and bass|breakbeat|synthwave)/.test(text)) {
      return theme(
        ['a nearly empty club at 3 a.m.', 'a neon highway', 'a dark warehouse', 'a late-night coding session', 'a city train after midnight'],
        ['hypnotic and pulse-driven', 'textural with a strong rhythmic spine', 'mechanical but warm', 'propulsive without getting frantic', 'deep, repetitive, and immersive'],
        ['keep the transitions seamless', 'favor interesting production details', 'avoid cheesy festival peaks', 'let the groove evolve gradually', 'stay focused on rhythm and texture']
      );
    }
    if (/(hip hop|rap|boom bap|trap|abstract hip hop|underground hip hop)/.test(text)) {
      return theme(
        ['a night drive through the city', 'a dusty record-store afternoon', 'a low-key house party', 'a long train ride', 'a late summer evening'],
        ['rhythm-first and production-heavy', 'dusty and sample-rich', 'bass-forward with sharp drums', 'left-field but still head-nodding', 'moody with strong pocket'],
        ['favor distinctive beats', 'avoid generic radio picks', 'keep the sequencing rhythmic', 'lean into deep cuts', 'let production style guide the transitions']
      );
    }
    if (/(punk|post-punk|garage|noise rock|post-hardcore)/.test(text)) {
      return theme(
        ['a tiny club with bad lighting', 'a fast drive across town', 'a half-empty dive bar', 'a cramped practice space', 'a gray afternoon with too much caffeine'],
        ['raw and kinetic', 'angular with strong momentum', 'scrappy but hooky', 'noisy without losing the song', 'tense and rhythm-forward'],
        ['avoid slick production', 'keep the energy moving', 'favor memorable guitar or bass lines', 'skip filler', 'stay rough around the edges']
      );
    }
    if (/(country|americana|folk|bluegrass|alt-country)/.test(text)) {
      return theme(
        ['a two-lane road at dusk', 'a quiet bar after last call', 'a hot afternoon with the windows down', 'a long rural drive', 'a porch after a storm'],
        ['warm and lived-in', 'dusty with strong storytelling', 'melodic and unpolished', 'rootsy without getting sleepy', 'plainspoken with some grit'],
        ['avoid glossy crossover production', 'favor strong songwriting', 'lean into deep cuts', 'keep the pacing natural', 'let the instrumentation feel human']
      );
    }
    if (/(jazz|fusion|bebop|soul jazz|spiritual jazz)/.test(text)) {
      return theme(
        ['a dim room after midnight', 'a rainy afternoon', 'a quiet dinner that turns strange', 'a late train ride', 'a small club near closing'],
        ['loose but purposeful', 'warm, intricate, and rhythmic', 'improvisational without losing direction', 'smoky and harmonically rich', 'restless but controlled'],
        ['favor strong interplay', 'avoid background-music blandness', 'let the arrangements breathe', 'keep a rhythmic thread', 'mix familiar language with stranger turns']
      );
    }
    return theme(
      ['a late-night drive', 'a gray afternoon', 'a long walk with headphones', 'a low-key weekend night', 'a road trip with no schedule'],
      ['coherent and characterful', 'melodic with some edge', 'deep-cut friendly', 'textured without losing momentum', 'distinctive rather than generic'],
      ['stay close to the artist’s musical neighborhood', 'favor deep cuts', 'make transitions feel intentional', 'avoid obvious filler', 'keep a consistent sonic thread']
    );
  }

  function buildIdea(artist) {
    const genres = Array.isArray(artist.genres) ? artist.genres : [];
    const primaryGenre = sample(genres);
    const theme = genreTheme(genres);
    const scene = sample(theme.scenes);
    const quality = sample(theme.qualities);
    const constraint = sample(theme.constraints);
    return Math.random() < 0.5
      ? `Start with ${artist.name}'s ${primaryGenre} side and build toward ${scene}; ${quality}, ${constraint}.`
      : `Build a ${primaryGenre} playlist around ${artist.name}: ${quality}; ${constraint}.`;
  }

  async function ensureIdeaProfiles() {
    if (ideaProfiles.length) return ideaProfiles;
    const response = await fetch('/api/prompt-profile', {cache: 'no-store'});
    const profile = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(profile.error || 'Could not load playlist ideas.');
    ideaProfiles = Array.isArray(profile.profiles)
      ? profile.profiles.filter(artist => artist?.name && Array.isArray(artist.genres) && artist.genres.length)
      : [];
    if (!ideaProfiles.length) throw new Error('No personalized playlist ideas are available yet.');
    return ideaProfiles;
  }

  document.addEventListener('DOMContentLoaded', () => {
    const picker = document.querySelector('#theme-select');
    const crtToggle = document.querySelector('#crt-toggle');
    const feedback = document.querySelector('#theme-feedback');

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
    ideaButton.textContent = 'Give Me Ideas';
    actions.insertBefore(ideaButton, generateButton);

    const clearButton = document.createElement('button');
    clearButton.type = 'button';
    clearButton.className = 'prompt-clear';
    clearButton.setAttribute('aria-label', 'Clear playlist prompt');
    clearButton.textContent = '×';
    composer.appendChild(clearButton);

    ideaButton.addEventListener('click', async () => {
      ideaButton.disabled = true;
      try {
        const profiles = await ensureIdeaProfiles();
        const alternatives = profiles.filter(artist => artist.name !== lastIdeaArtist);
        const artist = sample(alternatives.length ? alternatives : profiles);
        lastIdeaArtist = artist.name;
        promptBox.value = buildIdea(artist);
        promptBox.dispatchEvent(new Event('input', {bubbles: true}));
        promptBox.focus();
      } catch (error) {
        const status = document.querySelector('#status');
        if (status) status.textContent = error.message;
      } finally {
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
