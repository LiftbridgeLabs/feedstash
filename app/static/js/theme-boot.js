/* Sets the theme before the page paints, so it never flashes the wrong colors. Loaded as a plain (blocking)
   script in the <head>; theme.js takes over once the app starts. */
(function () {
  try {
    var saved = JSON.parse(localStorage.getItem('reader.theme') || '{}');
    var dark = saved.mode === 'dark'
      || (saved.mode !== 'light' && matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.dataset.mode = dark ? 'dark' : 'light';
    document.documentElement.dataset.scheme = saved.scheme || 'feedstash';
  } catch (err) {
    /* private mode, or storage turned off: the default theme is fine */
  }
})();
