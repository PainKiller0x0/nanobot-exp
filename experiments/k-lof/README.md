# K LOF Experiment

This is an experimental K-language spike for LOF premium history calculations.

Production stays in Rust. The K path is intentionally offline and optional:

1. Convert `premium_history.json` to CSV.
2. Compute a Python reference result for 7/14/30 recent samples.
3. If a K interpreter is available, run `premium_stats.k` and compare outputs.

The first target is historical premium stats, because it is vector/table shaped and easy to verify.

## Run

```bash
python3 experiments/k-lof/run_experiment.py \
  --history /root/.nanobot/workspace/skills/qdii-monitor/premium_history.json \
  --out-dir /tmp/k-lof
```

If you later install a K interpreter, pass it explicitly:

```bash
python3 experiments/k-lof/run_experiment.py \
  --history /root/.nanobot/workspace/skills/qdii-monitor/premium_history.json \
  --out-dir /tmp/k-lof \
  --k-bin /path/to/k
```

## Contract

Input CSV columns:

```text
code,date,premium_pct
```

Output JSON shape:

```json
{
  "generated_by": "python-reference",
  "windows": [7, 14, 30],
  "items": [
    {
      "code": "161129",
      "last_date": "2026-05-03",
      "w7": {"n": 7, "latest": 7.85, "avg": 6.12, "min": 4.3, "max": 7.85, "positive_days": 7}
    }
  ]
}
```
