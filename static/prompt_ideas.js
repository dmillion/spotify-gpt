(() => {
  const pick = values => values?.length ? values[Math.floor(Math.random() * values.length)] : '';
  const clean = value => String(value || '').trim();
  const uniq = values => [...new Set((values || []).map(clean).filter(Boolean))];

  const FAMILY_RULES = [
    {
      test: /(sludge|doom|stoner|desert rock|heavy psych|southern metal)/,
      vocab: ['riff-heavy', 'low-slung', 'fuzz-soaked', 'groove-first', 'thick in the low end', 'slow-burning but physical'],
      moves: ['favor big guitar figures and bass weight', 'keep the riffs memorable', 'let psych texture creep in without losing heft', 'stay dirty and physical rather than polished'],
    },
    {
      test: /(post-hardcore|hardcore|emo|screamo|noise rock|punk)/,
      vocab: ['ragged and cathartic', 'tense and guitar-driven', 'raw but melodic', 'abrasive with real hooks', 'live-wire and dynamic'],
      moves: ['favor wiry guitars and hard dynamic swings', 'keep the rhythm section urgent', 'look for hoarse or emotionally frayed delivery', 'avoid slick pop-punk polish'],
    },
    {
      test: /(black metal|post-black|atmospheric black)/,
      vocab: ['cold and expansive', 'raw but atmospheric', 'bleak with forward motion', 'melodic through the abrasion', 'windswept and severe'],
      moves: ['keep the atmosphere tense', 'favor long arcs that still move', 'let melody emerge through the noise', 'avoid glossy production'],
    },
    {
      test: /(death metal|grind|grindcore|powerviolence|metalcore)/,
      vocab: ['percussive and relentless', 'dense but sharply rhythmic', 'violent with groove underneath', 'compact and physical', 'ugly in a controlled way'],
      moves: ['favor memorable rhythmic turns', 'keep dead air to a minimum', 'lean into breakdowns or abrupt pivots', 'avoid overlong intros'],
    },
    {
      test: /(shoegaze|dream pop|slowcore|ethereal)/,
      vocab: ['hazy but melodic', 'washed-out and emotionally direct', 'soft-focus with strong hooks', 'layered and bittersweet', 'dreamy without going weightless'],
      moves: ['favor texture without sacrificing melody', 'let the sequence gradually deepen', 'keep transitions fluid', 'avoid bright pop detours'],
    },
    {
      test: /(psychedelic|psych rock|indie rock|alternative rock|americana|alt-country|southern rock)/,
      vocab: ['reverb-heavy and rootsy', 'expansive but song-first', 'warm, loose, and psychedelic', 'melodic with a little dust on it', 'open-road and guitar-rich'],
      moves: ['favor organic guitars and roomy production', 'let country/folk roots bleed into psychedelia', 'keep the songs strong even when the arrangements sprawl', 'avoid overly polished indie-rock filler'],
    },
    {
      test: /(post-rock|post-metal|instrumental rock)/,
      vocab: ['slow-building and massive', 'textural with a heavy payoff', 'patient but not static', 'wide-screen and dynamic', 'atmospheric with real weight'],
      moves: ['favor tension-and-release arcs', 'keep crescendos earned', 'look for strong recurring guitar themes', 'avoid shapeless ambient drift'],
    },
    {
      test: /(techno|house|electronic|idm|electro|dnb|drum and bass|breakbeat|synthwave)/,
      vocab: ['pulse-driven and textural', 'mechanical but warm', 'hypnotic with a strong rhythmic spine', 'deep and propulsive', 'repetitive in a purposeful way'],
      moves: ['let the groove evolve gradually', 'favor unusual production details', 'keep transitions seamless', 'avoid generic festival peaks'],
    },
    {
      test: /(hip hop|rap|boom bap|trap|abstract hip hop|underground hip hop)/,
      vocab: ['dusty and sample-rich', 'bass-forward with sharp drums', 'left-field but head-nodding', 'moody with a strong pocket', 'production-first and rhythm-heavy'],
      moves: ['favor distinctive beats', 'let production style guide the transitions', 'lean into deep cuts', 'avoid generic radio picks'],
    },
    {
      test: /(jazz|fusion|bebop|soul jazz|spiritual jazz)/,
      vocab: ['loose but purposeful', 'harmonically rich and rhythmic', 'restless but controlled', 'warm and intricate', 'improvisational without losing direction'],
      moves: ['favor strong ensemble interplay', 'keep a rhythmic thread', 'mix familiar language with stranger turns', 'avoid background-music blandness'],
    },
  ];

  function familyFor(genres) {
    const text = genres.join(' ').toLowerCase();
    return FAMILY_RULES.find(rule => rule.test.test(text)) || {
      vocab: ['distinctive and characterful', 'textured with real momentum', 'melodic with some edge', 'deep-cut friendly', 'cohesive without sounding generic'],
      moves: ['follow the strongest musical traits instead of broad genre labels', 'favor deep cuts with a clear connection', 'keep transitions musically legible', 'avoid generic similarity filler'],
    };
  }

  function soundPhrases(profile) {
    const sound = profile && typeof profile === 'object' ? profile : {};
    const phrases = [];
    const high = (key, text) => { if (Number(sound[key]) >= 68) phrases.push(text); };
    const low = (key, text) => { if (Number(sound[key]) <= 32) phrases.push(text); };
    high('bass_weight', 'keep the low end prominent');
    high('low_mid_weight', 'favor thick low-midrange guitars and body');
    high('brightness', 'keep some upper-end bite in the guitars or production');
    low('brightness', 'stay darker and less glassy in the top end');
    high('noise_texture', 'lean toward rougher, noisier textures');
    low('noise_texture', 'keep the texture comparatively clean and defined');
    high('rhythmic_density', 'favor busy, active rhythmic motion');
    low('rhythmic_density', 'leave more space between rhythmic events');
    high('tempo', 'keep the pace moving');
    low('tempo', 'stay on the slower, heavier side');
    return phrases;
  }

  function labelGenres(genres) {
    const useful = uniq(genres).filter(value => value.length <= 32);
    if (!useful.length) return '';
    if (useful.length === 1) return useful[0];
    return `${useful[0]} / ${useful[1]}`;
  }

  function buildRichIdea(artist) {
    const genres = uniq([
      ...(artist.genres || []),
      ...(artist.musicbrainz_tags || []),
      ...((artist.tags || []).map(tag => tag?.name)),
    ]);
    const family = familyFor(genres);
    const descriptor = pick(family.vocab);
    const move = pick(family.moves);
    const genreLabel = labelGenres(genres);
    const similar = uniq(artist.similar_artists || []).filter(name => name.toLowerCase() !== String(artist.name || '').toLowerCase());
    const neighbor = pick(similar);
    const measured = pick(soundPhrases(artist.sound_profile));
    const detail = measured || move;
    const name = artist.name;

    const genreClause = genreLabel ? `${genreLabel} side` : 'core sound';
    const neighborClause = neighbor ? ` Use ${neighbor} as one edge of the neighborhood, but don't let the playlist turn into a clone list.` : '';

    const templates = [
      `Start from ${name}'s ${genreClause}: keep it ${descriptor}, ${detail}, and branch into artists that share those specific traits rather than just the broad genre tag.${neighborClause}`,
      `Build around what makes ${name} distinctive — ${descriptor}. ${detail}; favor deep cuts and adjacent artists that preserve that feel while gradually widening the palette.${neighborClause}`,
      `Use ${name} as the anchor for a ${genreLabel || 'closely related'} set. Keep the first stretch ${descriptor}, then push outward through genuinely related sounds; ${detail}.${neighborClause}`,
      `Trace ${name}'s musical DNA instead of just their scene: ${descriptor}, with ${genreLabel || 'their strongest stylistic traits'} as the center. ${detail}; keep every detour explainably connected.${neighborClause}`,
      `Make a playlist that sounds like someone understood why ${name} works: ${descriptor}, ${detail}, and no generic "similar artists" filler. Broaden through neighboring textures, riffs, rhythms, or production choices.${neighborClause}`,
      `Take ${name}'s ${genreClause} and exaggerate one useful trait without losing the songs: ${descriptor}. ${detail}; sequence it so the relationship between tracks is obvious, not merely categorical.${neighborClause}`,
    ];
    return pick(templates);
  }

  // index.html owns rotation and artist selection; replacing this function keeps
  // that behavior while making each generated idea use the richer profile data.
  window.buildPromptIdea = buildRichIdea;
})();
