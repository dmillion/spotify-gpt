(() => {
  let runtime = {ollama_mode:'unknown', ollama_model:''};
  let runtimeRequest;
  let pending;
  const compact = value => new Intl.NumberFormat(undefined, {
    notation:'compact', maximumFractionDigits:1,
  }).format(value);

  async function loadRuntime() {
    try {
      const response = await fetch('/api/runtime', {cache:'no-store'});
      if (response.ok) runtime = await response.json();
    } catch (_) { /* Unknown mode keeps neutral wording. */ }
  }

  function explain() {
    const body = document.querySelector('.usage-body');
    if (!body) return;
    let explanation = body.querySelector('.usage-explainer');
    if (!explanation) {
      explanation = document.createElement('div');
      explanation.className = 'usage-explainer';
      for (const name of ['mode', 'meaning', 'limits', 'scope']) {
        const line = document.createElement('p');
        line.dataset.usageExplanation = name;
        explanation.appendChild(line);
      }
      body.appendChild(explanation);
    }
    const local = runtime.ollama_mode === 'local';
    const cloud = runtime.ollama_mode === 'cloud';
    const model = runtime.ollama_model ? ` · ${runtime.ollama_model}` : '';
    const copy = {
      mode: (local ? 'Running on this Mac' : cloud ? 'Ollama Cloud' : 'Ollama runtime not confirmed') + model,
      meaning:'Tokens are pieces of text. Input includes your prompt, instructions, and candidate tracks; output is the model’s reply. The bar shows the input/output split, not a remaining allowance.',
      limits:local
        ? 'Local inference has no per-token fee or monthly token quota. More tokens can mean longer waits and more memory use. Each request still has a context-window limit; these cumulative totals do not measure how full that window is.'
        : cloud
          ? 'Cloud inference can consume plan credits and has service limits, even on a free plan. This meter cannot show your remaining account allowance; check your Ollama account.'
          : 'Limits depend on whether the model runs locally or in the cloud. These totals do not show a remaining quota or context capacity.',
      scope:'Recorded Ollama calls from this app only, including earlier model configurations. Totals are cumulative; they update after a model response, not while it is generating.',
    };
    for (const [name, text] of Object.entries(copy)) {
      const node = explanation.querySelector(`[data-usage-explanation="${name}"]`);
      if (node.textContent !== text) node.textContent = text;
    }
  }

  async function update() {
    runtimeRequest ||= loadRuntime();
    await runtimeRequest;
    explain();
    try {
      const response = await fetch('/api/usage', {cache:'no-store'});
      if (!response.ok) throw new Error('Usage unavailable');
      const data = await response.json();
      for (const [id, key] of Object.entries({total:'total_tokens',today:'today_tokens',input:'input_tokens',output:'output_tokens'})) {
        const node = document.querySelector(`#usage-${id}`);
        const value = Number(data[key]) || 0;
        node.textContent = compact(value);
        node.title = `${value.toLocaleString()} tokens`;
        node.setAttribute('aria-label', node.title);
      }
      const total = data.input_tokens + data.output_tokens;
      document.querySelector('#usage-input-bar').style.width = `${total ? data.input_tokens / total * 100 : 0}%`;
      document.querySelector('#usage-output-bar').style.width = `${total ? data.output_tokens / total * 100 : 0}%`;
      document.querySelector('#usage-detail').textContent = data.requests
        ? `${data.requests.toLocaleString()} model responses recorded${data.latest ? ` · Latest: ${data.latest.total_tokens == null ? 'usage unavailable' : data.latest.total_tokens.toLocaleString() + ' tokens'} (${data.latest.model})` : ''}${data.unreported_requests ? ` · ${data.unreported_requests} responses without counts` : ''}`
        : 'No token usage recorded yet.';
    } catch (_) {
      document.querySelector('#usage-detail').textContent = 'Usage unavailable. Displayed counts may be out of date.';
    }
  }
  window.TuneRaiderUsage = {
    refresh() {
      if (!pending) pending = update().finally(() => { pending = null; });
      return pending;
    },
  };
})();
