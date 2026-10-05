/* SadlerACME appearance only. Runs before CSS to apply the saved palette.
 * One browser-local value, no credentials, no API calls, no DOM reconstruction.
 * A blocked/unavailable storage API must never stop the application. */
(function () {
  'use strict';
  var key = 'sadleracme.theme';
  var root = document.documentElement;
  function palette(value) { return value === 'light' ? 'light' : 'dark'; }
  function update(value) {
    value = palette(value);
    root.setAttribute('data-theme', value);
    var meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) meta.setAttribute('content', value);
    var button = document.getElementById('themeToggle');
    if (button) {
      var next = value === 'dark' ? 'light' : 'dark';
      button.setAttribute('aria-label', 'Switch to ' + next + ' mode');
      button.setAttribute('title', 'Switch to ' + next + ' mode');
      var label = button.querySelector('.theme-label');
      if (label) label.textContent = next === 'light' ? 'Light mode' : 'Dark mode';
    }
  }
  var initial = 'dark';
  try { initial = palette(window.localStorage.getItem(key)); } catch (e) { /* memory-only */ }
  update(initial);
  function bind() {
    update(root.getAttribute('data-theme'));
    var button = document.getElementById('themeToggle');
    if (button) button.addEventListener('click', function () {
      var value = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      update(value);
      try { window.localStorage.setItem(key, value); } catch (e) { /* this page still switches */ }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
  window.addEventListener('storage', function (event) {
    if (event.key === key || event.key === null) update(event.newValue);
  });
})();
