#!/usr/bin/env python3
"""Analyze docker-stats logs produced by /usr/local/bin/docker-stats-log.sh.

Log format (one line per container per timestamp):

    2026-09-10 07:40:01 frontend-iwwc8cg4cwcc40css4w0k0o4 0.00% 7.867MiB / 15.25GiB 225kB / 291kB

Fields after the container name: CPU%, mem used / mem limit, net in / net out.

Usage:
    python3 scripts/analyze_docker_stats.py ~/Downloads/docker-stats.log
    python3 scripts/analyze_docker_stats.py ~/Downloads/docker-stats.log* --container prometheus
    python3 scripts/analyze_docker_stats.py log --by-name            # strip stack suffixes
    python3 scripts/analyze_docker_stats.py log --plot mem.png       # requires matplotlib

Requires pandas; matplotlib only for --plot.
"""

import argparse
import glob
import re
import sys
from pathlib import Path

import pandas as pd

LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<container>\S+)\s+"
    r"(?P<cpu>[\d.]+)%\s+"
    r"(?P<mem>[\d.]+\s?[kMGTP]?i?B)\s*/\s*(?P<mem_limit>[\d.]+\s?[kMGTP]?i?B)\s+"
    r"(?P<net_in>[\d.]+\s?[kMGTP]?i?B)\s*/\s*(?P<net_out>[\d.]+\s?[kMGTP]?i?B)\s*$"
)

UNITS = {"B": 1, "kB": 1e3, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12,
         "kiB": 2**10, "MiB": 2**20, "GiB": 2**30, "TiB": 2**40}


def parse_size(s: str) -> float:
    """'1.304GiB' -> bytes (float)."""
    m = re.match(r"^([\d.]+)\s?(\S+)$", s.strip())
    if not m:
        return float("nan")
    return float(m.group(1)) * UNITS.get(m.group(2), 1)


def load(paths: list[str], by_name: bool = False) -> pd.DataFrame:
    rows = []
    for pattern in paths:
        for p in glob.glob(pattern):
            for line in Path(p).read_text(errors="replace").splitlines():
                m = LINE_RE.match(line)
                if not m:
                    continue
                rows.append({
                    "ts": pd.to_datetime(m.group("ts")),
                    "container": m.group("container"),
                    "cpu_pct": float(m.group("cpu")),
                    "mem_bytes": parse_size(m.group("mem")),
                    "mem_limit_bytes": parse_size(m.group("mem_limit")),
                    "net_in_bytes": parse_size(m.group("net_in")),
                    "net_out_bytes": parse_size(m.group("net_out")),
                })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    if by_name:
        # Strip stack-suffix: 'redis-iwwc8cg4cwcc40css4w0k0o4' -> 'redis'
        df["container"] = df["container"].str.replace(r"-[a-z0-9]{20,}$", "", regex=True)
    return df.sort_values("ts")


def fmt_mb(b: float) -> str:
    return f"{b / 2**20:,.1f} MiB"


def summarize(df: pd.DataFrame, top: int = 30) -> None:
    if df.empty:
        print("No parseable lines found.")
        return

    print(f"Samples: {len(df)}   containers: {df['container'].nunique()}   "
          f"span: {df['ts'].min()} -> {df['ts'].max()}\n")

    per = (df.groupby("container")
             .agg(cpu_mean=("cpu_pct", "mean"),
                  cpu_max=("cpu_pct", "max"),
                  mem_mean=("mem_bytes", "mean"),
                  mem_max=("mem_bytes", "max"),
                  mem_std=("mem_bytes", "std"))
             .sort_values("mem_max", ascending=False))

    per["cpu_mean"] = per["cpu_mean"].map("{:.2f}".format)
    per["cpu_max"] = per["cpu_max"].map("{:.2f}".format)
    per["mem_mean"] = per["mem_mean"].map(fmt_mb)
    per["mem_max"] = per["mem_max"].map(fmt_mb)
    per["mem_std"] = per["mem_std"].map(fmt_mb)

    print("=== Per-container (sorted by peak memory) ===")
    print(per.head(top).to_string())

    # Whole-stack memory per timestamp — the sizing number.
    stack = df.groupby("ts")["mem_bytes"].sum()
    print("\n=== Whole-stack memory (all containers summed per timestamp) ===")
    print(f"mean={fmt_mb(stack.mean())}  max={fmt_mb(stack.max())}  "
          f"p95={fmt_mb(stack.quantile(0.95))}  min={fmt_mb(stack.min())}")

    busy = (df.groupby("container")["cpu_pct"].mean()
              .sort_values(ascending=False).head(5))
    print("\n=== Top 5 by mean CPU ===")
    print(busy.map("{:.2f}%".format).to_string())

    # CPU spikes: timestamps where any container exceeds a rough threshold.
    spikes = df[df["cpu_pct"] > 50][["ts", "container", "cpu_pct"]]
    if not spikes.empty:
        print("\n=== CPU spikes > 50% ===")
        print(spikes.to_string(index=False))


def plot(df: pd.DataFrame, out: str, by_name: bool) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True)
    for name, g in df.groupby("container"):
        axes[0].plot(g["ts"], g["mem_bytes"] / 2**20, label=name, lw=1)
        axes[1].plot(g["ts"], g["cpu_pct"], label=name, lw=1)
    axes[0].set_ylabel("Memory (MiB)")
    axes[1].set_ylabel("CPU (%)")
    axes[1].set_xlabel("Time (UTC)")
    if by_name:
        axes[0].legend(ncol=3, fontsize=8)
    else:
        axes[0].legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print(f"Plot written to {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="log file(s)/glob(s)")
    ap.add_argument("--by-name", action="store_true",
                    help="strip stack suffix from container names")
    ap.add_argument("--plot", metavar="OUT.png",
                    help="write a mem/CPU timeline chart (needs matplotlib)")
    ap.add_argument("--top", type=int, default=30, help="rows in per-container table")
    args = ap.parse_args()

    df = load(args.files, by_name=args.by_name)
    summarize(df, top=args.top)
    if args.plot:
        plot(df, args.plot, args.by_name)


if __name__ == "__main__":
    sys.exit(main())
