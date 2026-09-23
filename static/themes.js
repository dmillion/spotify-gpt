/* Apply before first paint; theme choice never reloads or resets the playlist form. */
(() => {
  const key = 'mixtape-foundry-theme';
  const themes = ['foundry', 'deep-space', 'amber'];
  let selected = 'deep-space';
  try {
    const saved = localStorage.getItem(key);
    if (themes.includes(saved)) selected = saved;
  } catch { /* Themes still work when browser storage is unavailable. */ }
  document.documentElement.dataset.theme = selected;

  document.addEventListener('DOMContentLoaded', () => {
    const picker = document.querySelector('#theme-select');
    if (!picker) return;
    picker.value = selected;
    picker.addEventListener('change', () => {
      if (!themes.includes(picker.value)) return;
      document.documentElement.dataset.theme = picker.value;
      const feedback = document.querySelector('#theme-feedback');
      try {
        localStorage.setItem(key, picker.value);
        feedback.textContent = `${picker.selectedOptions[0].textContent} theme selected and saved.`;
      } catch {
        feedback.textContent = `${picker.selectedOptions[0].textContent} theme selected for this page. Your browser could not save the preference.`;
      }
    });
    window.addEventListener('storage', event => {
      if (event.key !== key) return;
      const theme = themes.includes(event.newValue) ? event.newValue : 'deep-space';
      document.documentElement.dataset.theme = theme;
      picker.value = theme;
    });
  });
})();
