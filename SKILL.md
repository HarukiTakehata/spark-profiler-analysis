---
name: spark-profiler-analysis
description: Analyze Minecraft Spark profiler reports.
version: 1.0.0
author: Yang_161941 (GitHub user)
license: MIT
platforms: [linux, macos]
tags: [minecraft, spark, profiling, performance]
---

# Spark Profiler Analysis Skill

Analyze Minecraft Spark profiler/sampler reports from `https://spark.lucko.me/<code>`. This skill covers both **sampler** (time-series health metrics) and **profiler** (call-stack sampling) reports. It extracts performance bottlenecks, memory pressure, entity load, platform info, and actionable recommendations.

## When to Use

- A user sends you a Spark link (`spark.lucko.me/<code>`) and asks for a performance analysis.
- You are troubleshooting server lag (low TPS, high MSPT, memory spikes) and need data-driven diagnostics.
- You want to check if specific mods, entities, or GC patterns are causing performance problems.

## Prerequisites

- A valid Spark profiler/sampler report URL (`https://spark.lucko.me/<code>`).
- `curl` and `python3` available in the terminal.
- No API key needed — the raw data is public via `?raw=true` query parameter.

## How to Run

This is a two-phase analysis:

**Phase 1 — Metrics (terminal)**: Fetch raw JSON for TPS, MSPT, memory, GC pools, entities, mods.
**Phase 2 — Call-stack (browser)**: Extract the profiler tree from the spark-viewer DOM using JavaScript.

The raw JSON (`?raw=true`) does NOT include the profiler call-stack — it must be extracted from the browser-rendered page.

## Quick Reference

| Check | What to look for |
|-------|-----------------|
| TPS | `< 18` = lagging, `< 10` = severe |
| MSPT median | `> 50ms` = tick loop overload |
| MSPT max | `> 100ms` = stutter spikes (check GC/tick pause) |
| Heap usage | `> 85%` = likely GC pressure |
| Entity count | `> 500` in one dimension = potential lag |
| CPU process | `> 80%` = computation-bound |
| `profiler` data | Call-stack tree shows exact hot methods |

## Procedure

### Step 1: Get the overview via browser

Use `browser_navigate` to open the Spark URL. Key info visible on the page:
- Server name, date, interval
- TPS, MSPT (min/med/95%ile/max)
- CPU and memory usage
- Entity counts and TPS/MSPT timeline chart

### Step 2: Fetch raw JSON data

Use `terminal` with `curl`:
```bash
curl -s -L "https://spark.lucko.me/<code>?raw=true"
```

Pipe through Python for structured analysis. Always check the `type` field:
- `"sampler"` — time-series health data (TPS, MSPT, memory, entities, CPU)
- `"profiler"` — call-stack sampling (method-level hot spots)

### Step 3: Extract key metrics (sampler type)

From `metadata.platformStatistics`:
- **TPS**: `tps.last1m / last5m / last15m` (target: ≥ 20)
- **MSPT**: `mspt.last1m.mean / median / max / percentile95`
  - median > 50ms → tick loop is overloaded
  - max > 200ms → look for GC pauses or single-tick spikes
- **Memory**: `memory.heap.used / committed` — ratio > 85% means GC pressure
- **CPU**: `metadata.systemStatistics.cpu.processUsage.last1m`
- **Entities**: `world.totalEntities` and `entityCounts` for distribution
- **Platform**: `platform.name / version / minecraftVersion`
- **Sources**: `sources` — full mod list (count and key mods)

### Step 3b: Extract GC pool-level details

The raw JSON includes detailed GC memory pool data under `metadata.platformStatistics.memory.pools[]`. Always extract this — it reveals WHERE memory pressure lives:

```python
pools = ps['memory']['pools']
for pool in pools:
    name = pool['name']           # e.g. "G1 Eden Space", "G1 Old Gen"
    used = pool['usage']['used']
    committed = pool['usage']['committed']
    ratio = used/committed*100 if committed > 0 else 0
    print(f"{name}: {used/1e9:.1f}GB/{committed/1e9:.1f}GB ({ratio:.0f}%)")
```

Key signal: **G1 Old Gen > 90% used** → Full GC imminent, likely root cause of MSPT max spikes.

### Step 4: Extract profiler call-stack tree (browser — REQUIRED)

**The `?raw=true` JSON does NOT contain the profiler call-stack tree.** The call-stack data is decoded client-side by the spark-viewer (a Next.js app) and rendered into the DOM. You MUST use browser tools to extract it.

#### 4a: Get the overview

After `browser_navigate` to the Spark URL, the page shows live-updating TPS/MSPT/memory. The profiler tree is in the "All View" section below the separator. Expand key nodes by clicking.

#### 4b: Expand the tree node by node

The DOM structure: `.stack` div > `li` elements > `.node-info` clickable divs. Each `.node-info` div has an onclick handler. Click them programmatically via `browser_console`:

```javascript
// Find and click a specific node by matching text
var divs = document.querySelector('.stack').querySelectorAll('div');
divs.forEach(function(div) {
  if (div.textContent.includes('ServerLevel.tick()')) {
    div.click();
  }
});
```

#### 4c: Extract the full expanded tree

Once nodes are expanded, use the DOM walker script (`references/extract-tree.js`). Run via `browser_console`:

```javascript
var stack = document.querySelector('.stack');
var lis = stack.querySelectorAll('li');
var result = [];
lis.forEach(function(li) {
  var nodeInfo = li.querySelector('.node-info, div');
  if (!nodeInfo) return;
  var text = nodeInfo.textContent.trim();
  var match = text.match(/(\d+\.?\d*)%/);
  if (!match) return;
  var pct = parseFloat(match[1]);
  if (pct < 0.05) return;
  var depth = 0, el = li;
  while (el && el !== stack) {
    if (el.tagName === 'UL') depth++;
    el = el.parentElement;
  }
  result.push({depth: depth, pct: pct, text: text.substring(0, 250)});
});
JSON.stringify(result, null, 1);
```

#### 4d: Expansion strategy — follow the percentage chain

1. `Server thread 100%` → `Thread.run() ~96%` → `tickServer() ~93%`
2. → `tickChildren() ~90%` → `ServerLevel.tick() ~86%`
3. → `EntityTickList.forEach() ~56%` ← **usually the #1 hotspot**
4. Also expand `tickBlockEntities()` and `ServerChunkCache.tick()`
5. For each major hotspot, expand one more level to see if it breaks down by mod

#### 4e: Cross-reference with entity/mod data

Entity counts from Step 3 + `EntityTickList.forEach()` dominance = entity count IS the bottleneck. List top 20 entities with mod sources so recommendations are specific (e.g., "Quark's glass_frame + stoneling + torettoise = 192 entities").

#### 4f: Mods view — reliable flat extraction (RECOMMENDED when all-view fails)

When the "all" view tree won't expand reliably (nodes toggle unpredictably, DOM restructures, or browser_snapshot truncates mid-tree), switch to the **"mods" view**. It renders a flat list of `<h2>` (mod name + version) + `<li>` (Server thread percentage) pairs — no expansion needed, all entries visible immediately.

1. Click the "mods" tab in the spark-viewer (ref shown as "mods" in the snapshot).
2. Extract via `browser_console` with the snippet from `references/extract-mods-view.js`.

The mods view is comprehensive: it covers all mods that had any CPU time. **Important**: mod percentages exclude GC time, `unknown_Java`, and `not_walkable_Java` native overhead. When combining with the all-view breakdown, add those separately. A report where mods sum to ~50% + GC_active 10% + unknown_Java 2% = ~62% of total is normal — the remaining ~38% is vanilla Minecraft + NeoForge framework code appearing under the "neoforge" mod heading.

### Step 5: Formulate recommendations

| Finding | Recommendation |
|---------|---------------|
| Heap > 85% used | Increase `-Xmx`, check for memory leaks, reduce entity counts |
| MSPT max > 500ms | Check GC logs, look for single-tick heavy operations |
| Profiler shows specific mod methods | Target optimization at that mod's config or replace it |
| High entity count | Use entity limiting mods, reduce spawn rates |
| Low TPS + normal MSPT | Check network/disk I/O, redstone ticks |
| CPU > 80% process | Computation-bound server, consider reducing mod complexity |

## Pitfalls

- **❌ Raw JSON has NO profiler tree**: The `?raw=true` endpoint returns sampler metadata only (TPS, MSPT, memory, entities, mods). It does NOT contain the method-level call-stack tree. The call-stack is decoded client-side by the spark-viewer (Next.js) and rendered into the DOM. You MUST use browser interaction to extract it. The old guidance about `data["profiler"]["profile"]` only applies to the in-game spark mod's internal data structure — it is NOT present in the web API response.
- **Sampler vs Profiler**: A *sampler* report only has aggregate metrics (TPS/MSPT/memory). A *profiler* report has method-level call stacks. Check `data["type"]` to know which you have. However, even a sampler-type report shows a call tree in the browser — the spark-viewer renders profiler data regardless of the JSON type field.
- **`browser_snapshot` truncation**: The accessibility tree snapshots truncate at ~400 lines. Deep profiler trees (10+ nesting levels, 50+ nodes) will be cut off. Do NOT rely on repeated `browser_snapshot(full=true)` for tree extraction. Use `browser_console` with DOM-walking JavaScript instead (see `references/extract-tree.js`).
- **Re-expanding after view switch**: Switching between "all" / "flat" / "mods" views in the spark-viewer resets the expand/collapse state of the tree. If you need to switch views, re-extract the tree from scratch.
- **Interval mismatch**: The page shows "interval 4ms" which is the sampling interval for the profiler data. The tick loop (game loop) is separate — MSPT values are calculated over the actual server tick rate, not the profiler sample rate.
- **`curl | python3` pipe**: The security scanner (`tirith`) may flag `curl | python3` pipes. If blocked, use `tirith run <url>` or `vet <url>` as suggested. Save JSON to a temp file first: `curl -s -o /tmp/spark.json <url>` then `python3` to parse.
- **Truncated data**: For very long profiles (>30 min with short intervals), the raw JSON can be large. Sample or parse incrementally.
- **`timeseriesData`**: Timeseries graphs are rendered client-side from embedded arrays, not available as raw JSON.
- **entityCounts vs worlds**: `entityCounts` is the raw tick count; `worlds[*].totalEntities` may differ due to chunk-level aggregation — cross-reference both.
- **`sources` is a dict, not a list**: In the raw JSON, `metadata.sources` is keyed by mod ID (e.g. `{"create": {...}, "quark": {...}}`). Iterate with `.items()` or `.values()`, not as a list — assuming it's a list will crash with `KeyError: 0`.
- **`playerCount` may be a plain int**: It can be `2` (an int) rather than `{"online": 2, "max": 20}` (a dict). Guard with `isinstance(pc, dict)` before calling `.get()` on it.
- **GC stats are in the raw JSON**: `metadata.platformStatistics.gc` has per-generation breakdowns (`total`, `avgTime`, `avgFrequency`) — always extract these. An Old Gen GC averaging >100ms with frequency <60s is a red alert.
- **Mods view allocates vanilla+Minecraft+NeoForge under "neoforge"**: The mod named "neoforge (vX.Y.Z)" in the mods view carries all vanilla Minecraft + NeoForge framework code. Don't treat it as NeoForge-specific overhead.


## Verification

After analysis, confirm you can answer:
1. What is the server platform and Minecraft version?
2. What are the TPS/MSPT/memory stats?
3. Is there a specific performance bottleneck (method, entity, mod)?
4. What is the top actionable recommendation?
5. If profiler data exists, which methods consume the most CPU time?
