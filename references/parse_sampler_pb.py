#!/usr/bin/env python3
"""Parse spark.lucko.me sampler protobuf (schema verified 2026-08-26 against lucko/spark@master).

Usage: python3 parse_sampler_pb.py <report.pb> [code]
Requires: pip install grpcio-tools protobuf ; protos compiled to ./spark_proto/spark/*_pb2.py
Compile: cd spark_proto && python3 -m grpc_tools.protoc -I. --python_out=. spark/spark.proto spark/spark_sampler.proto

Schema notes (current master):
- children_refs are POSITIONAL INDEXES into that thread's children pool (StackTraceNode has NO id field).
- SamplerMetadata fields: platform_metadata, platform_statistics, system_statistics, sources(map),
  start_time/end_time (epoch MILLIseconds), interval(us), number_of_ticks.
- WindowStatistics fields: ticks, cpu_process(frac), cpu_system, tps, mspt_median, mspt_max,
  players, entities, tile_entities(-1 if n/a), chunks, start_time, end_time, duration(ms).
- node.times[] is aligned 1:1 with SamplerData.time_windows order (all arrays same length).
- Self time must be computed PER WINDOW: node.times[p] - sum(children.times[p]).
"""
import sys, statistics, math
sys.path.insert(0, "./spark_proto")
from spark import spark_sampler_pb2 as pb


def main(path):
    data = pb.SamplerData()
    with open(path, "rb") as f:
        data.ParseFromString(f.read())
    cs = dict(data.class_sources)
    pm = data.metadata.platform_metadata
    print(f"{pm.name} {pm.version} mc {pm.minecraft_version}")
    md = data.metadata
    dur_ms = md.end_time - md.start_time
    print(f"profile span {(dur_ms)/60000:.1f} min, interval {md.interval}us")

    tw = data.time_window_statistics
    keys = sorted(tw.keys())
    print(f"windows={len(keys)} tps_mean={statistics.mean(tw[k].tps for k in keys):.2f} "
          f"mspt_med_mean={statistics.mean(tw[k].mspt_median for k in keys):.1f}")

    th = next(t for t in data.threads if "Server thread" in (t.name or ""))
    pool = list(th.children)
    W = len(data.time_windows)
    roots = [i for i in th.children_refs if 0 <= i < len(pool)]
    root_total = sum(sum(pool[i].times) for i in roots)

    def label(i):
        n = pool[i]
        s = cs.get(n.class_name)
        return f"{n.class_name.rsplit('.', 1)[-1]}.{n.method_name}" + (f" [{s}]" if s else "")

    # self time per node (aggregate over windows)
    self_t = {}
    for i, n in enumerate(pool):
        kids = sum(sum(pool[c].times) for c in n.children_refs if 0 <= c < len(pool))
        self_t[i] = max(sum(n.times) - kids, 0.0)

    print("\nTOP 20 SELF TIME:")
    for i, s in sorted(self_t.items(), key=lambda kv: -kv[1])[:20]:
        if s <= 0:
            break
        print(f"  {label(i)}  {s/1000:.1f}s ({s/root_total*100:.1f}%)")

    def dump(idx, depth, parent_ms, out, max_depth=14, min_frac_root=0.0015, min_frac_parent=0.05):
        t = sum(pool[idx].times)
        if depth > max_depth or t / root_total < min_frac_root:
            return
        if parent_ms and t / parent_ms < min_frac_parent:
            return
        out.append("  " * depth + f"{label(idx)}  {t/1000:.1f}s {t/root_total*100:.1f}%")
        for c in sorted(pool[idx].children_refs, key=lambda c: -sum(pool[c].times)):
            if 0 <= c < len(pool):
                dump(c, depth + 1, t, out, max_depth, min_frac_root, min_frac_parent)

    print("\nTREE:")
    out = []
    for r in sorted(roots, key=lambda i: -sum(pool[i].times)):
        dump(r, 0, root_total, out)
    print("\n".join(out[:120]))

    # per-window mod self share + correlation with mspt (aligned arrays!)
    win_order = list(data.time_windows)
    kt_cache = {}

    def kids_arr(i):
        if i not in kt_cache:
            arr = [0.0] * W
            for c in pool[i].children_refs:
                if 0 <= c < len(pool):
                    ct = pool[c].times
                    for p in range(W):
                        arr[p] += ct[p]
            kt_cache[i] = arr
        return kt_cache[i]

    def pkg(cls):
        if cls.startswith("net.minecraft"):
            return "vanilla"
        if cls.split(".")[0] in ("java", "javax", "sun", "jdk"):
            return "jdk"
        return None

    mod_self = [dict() for _ in range(W)]
    for i, n in enumerate(pool):
        ka = kids_arr(i)
        src = cs.get(n.class_name) or pkg(n.class_name) or "native"
        for p in range(W):
            s = n.times[p] - ka[p]
            if s > 0:
                mod_self[p][src] = mod_self[p].get(src, 0.0) + s

    tot = [sum(m.values()) for m in mod_self]
    tgt = input_mod if (input_mod := None) else "ae2"
    series = [mod_self[p].get(tgt, 0.0) / max(tot[p], 1) for p in range(W)]
    mspt = [tw[k].mspt_median for k in win_order]

    def corr(a, b):
        ma, mb = statistics.mean(a), statistics.mean(b)
        num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
        return num / den if den else 0

    print(f"\ncorr({tgt} self-share, mspt_median) = {corr(series, mspt):.3f}")
    print("timeline x10 windows:")
    for b in range(0, W, 10):
        seg = slice(b, b + 10)
        print(f"  {b}-{b+10}: mspt={statistics.mean(mspt[seg]):.0f} "
              f"{tgt}_share={statistics.mean(series[seg])*100:.0f}%")


if __name__ == "__main__":
    main(sys.argv[1])
