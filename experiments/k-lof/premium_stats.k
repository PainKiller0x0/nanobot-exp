/ Experimental K kernel for LOF premium history stats.
/ Contract-first file: the Python harness owns verification and may skip this
/ when no K interpreter is installed.
/
/ Expected argv-like convention for compatible K runners:
/   premium_stats.k input.csv output.json
/
/ Intended calculation:
/   - read code,date,premium_pct rows
/   - group by code
/   - sort each group by date descending
/   - for windows 7 14 30, compute n/latest/avg/min/max/positive_days
/
/ Different open-source K implementations differ in CSV/JSON helpers, so this
/ file is deliberately small and keeps the algorithm contract here. When we
/ choose a concrete runtime (ngn/k, kona, ktye, or q), this file should become
/ executable and `run_experiment.py --k-bin ...` will compare it with Python.
