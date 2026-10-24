
  // Apply saved theme before first paint to avoid a flash.
  // NOTE: accessing localStorage THROWS in Firefox when site storage is blocked
  // (strict tracking protection / blocked cookies), so it must be guarded — an
  // unguarded access here would abort the script and leave a blank/broken UI.
  (function () {
    var t = 'dark';
    try { t = localStorage.getItem('theme') || 'dark'; } catch (e) {}
    document.documentElement.setAttribute('data-theme', t);
  })();
