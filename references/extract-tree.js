// Spark Profiler Tree Extractor
// Run via browser_console on a spark.lucko.me page with the profiler tree expanded.
// Expands nodes and extracts the full call-stack tree as structured JSON.

(function() {
  var stack = document.querySelector('.stack');
  if (!stack) return JSON.stringify({error: 'No .stack element found — is the profiler page loaded?'});

  var lis = stack.querySelectorAll('li');
  var result = [];
  
  lis.forEach(function(li) {
    var nodeInfo = li.querySelector('.node-info, div');
    if (!nodeInfo) return;
    
    var text = nodeInfo.textContent.trim();
    
    // Extract percentage
    var pctMatch = text.match(/(\d+\.?\d*)%/);
    if (!pctMatch) return;
    var pct = parseFloat(pctMatch[1]);
    if (pct < 0.05) return; // filter noise below 0.05%
    
    // Extract time in ms
    var msMatch = text.match(/(\d+)ms/);
    var ms = msMatch ? parseInt(msMatch[1]) : 0;
    
    // Extract self time
    var selfMatch = text.match(/self:\s*(\d+)ms/);
    var selfMs = selfMatch ? parseInt(selfMatch[1]) : null;
    
    // Calculate nesting depth by counting parent UL elements up to .stack
    var depth = 0;
    var el = li;
    while (el && el !== stack) {
      if (el.tagName === 'UL') depth++;
      el = el.parentElement;
    }
    
    result.push({
      depth: depth,
      pct: pct,
      ms: ms,
      self_ms: selfMs,
      text: text.substring(0, 250)
    });
  });
  
  return JSON.stringify(result, null, 1);
})();
