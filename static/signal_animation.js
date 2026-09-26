(() => {
  function installSignalRunner() {
    const svg = document.querySelector('.signal-panel svg');
    const base = svg?.querySelector('.signal-primary');
    if (!svg || !base || svg.querySelector('.signal-primary-runner')) return;

    const runner = base.cloneNode(false);
    runner.classList.remove('signal-primary');
    runner.classList.add('signal-primary-runner');
    base.insertAdjacentElement('afterend', runner);

    const style = document.createElement('style');
    style.id = 'signal-runner-styles';
    style.textContent = `
      :root {
        --signal-primary-trail:180;
      }
      .signal-primary {
        opacity:.34 !important;
        animation:none !important;
        filter:none !important;
        stroke-width:1 !important;
      }
      .signal-primary-runner {
        fill:none;
        stroke:currentColor;
        stroke-width:1.8;
        vector-effect:non-scaling-stroke;
        stroke-linecap:round;
        stroke-dasharray:var(--signal-primary-trail) 1900;
        stroke-dashoffset:var(--signal-primary-trail);
        opacity:.95;
        filter:drop-shadow(0 0 4px var(--crt-glow));
        animation:signal-runner var(--signal-primary-duration) linear infinite;
        will-change:stroke-dashoffset;
      }
      @keyframes signal-runner {
        from { stroke-dashoffset:var(--signal-primary-trail); }
        to { stroke-dashoffset:-1900; }
      }
    `;
    document.head.appendChild(style);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', installSignalRunner, {once:true});
  } else {
    installSignalRunner();
  }
})();
