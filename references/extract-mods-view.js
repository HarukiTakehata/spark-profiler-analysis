// Extract mod CPU percentages from the spark-viewer "mods" view.
// Run via browser_console after clicking the "mods" tab.
// Returns a newline-separated ranked list: "PCT% mod_name (version)"

(function() {
  var headings = document.querySelectorAll('h2');
  var results = [];
  headings.forEach(function(h2) {
    var text = h2.textContent.trim();
    // Find the next LI sibling (skipping non-LI elements between h2 and li)
    var next = h2.nextElementSibling;
    while (next && next.tagName !== 'H2' && next.tagName !== 'LI') {
      next = next.nextElementSibling;
    }
    if (next && next.tagName === 'LI') {
      var pctMatch = next.textContent.match(/(\d+\.?\d*)%/);
      if (pctMatch) {
        results.push({mod: text, pct: parseFloat(pctMatch[1])});
      }
    }
  });
  results.sort(function(a,b){return b.pct - a.pct;});
  return results.map(function(r){return r.pct.toFixed(2) + '% ' + r.mod;}).join('\n');
})();
