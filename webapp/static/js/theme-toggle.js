document.addEventListener('DOMContentLoaded', () => {
  const themeLink = document.getElementById('theme-link');
  const toggleBtn = document.getElementById('theme-toggle');

  // Vorher gespeichertes Theme laden (falls vorhanden), Standard ist 'dark'
  const savedTheme = localStorage.getItem('theme') || 'dark';
  applyTheme(savedTheme);

  // Klick-Event für den Toggle-Button
  toggleBtn.addEventListener('click', () => {
    // Aktuelles CSS prüfen
    const currentTheme = themeLink.getAttribute('href').includes('dark.css') 
      ? 'dark' 
      : 'light';

    // Umschalten
    const newTheme = (currentTheme === 'dark') ? 'light' : 'dark';
    applyTheme(newTheme);
  });

  function applyTheme(theme) {
    if (theme === 'light') {
      themeLink.setAttribute('href', '/static/css/light.css');
      toggleBtn.textContent = 'Dark';
      localStorage.setItem('theme', 'light');
    } else {
      themeLink.setAttribute('href', '/static/css/dark.css');
      toggleBtn.textContent = 'Light';
      localStorage.setItem('theme', 'dark');
    }
  }
});
