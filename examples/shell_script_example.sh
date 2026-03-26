#!/bin/bash
# Pure shell script example — no Python required during the run.
#
# Shows that expTrack works with any workload: C++, Fortran, Julia, R,
# compiled binaries, or plain shell commands. Only the exptrack CLI
# calls need Python (they're quick one-shot commands).
#
# Run with: bash examples/shell_script_example.sh

set -euo pipefail

# ── Start tracking ────────────────────────────────────────────────────────
eval $(exptrack run-start \
    --script simulation \
    --tags shell non-python \
    --iterations 1000 \
    --tolerance 1e-6 \
    --method conjugate-gradient)

echo "Experiment: $EXP_NAME ($EXP_ID)"
echo "Output dir: $EXP_OUT"

# ── Trap for failure reporting ────────────────────────────────────────────
cleanup() {
    exit_code=$?
    if [ $exit_code -ne 0 ]; then
        exptrack run-fail "$EXP_ID" "Exit code $exit_code"
    fi
}
trap cleanup EXIT

# ── Run your workload (any language / binary) ─────────────────────────────
# This is where you'd run your actual computation. Examples:
#   ./build/simulate --config params.yaml
#   julia solve.jl --tol 1e-6
#   Rscript analysis.R
#   make run ARGS="--iterations 1000"

# Simulating a computation that writes results
mkdir -p "$EXP_OUT"
echo "Running simulation..."
for i in $(seq 1 5); do
    # Simulate: compute a metric and log it
    error=$(echo "scale=6; 1.0 / ($i * $i)" | bc)
    exptrack log-metric "$EXP_ID" residual_error "$error" --step "$i"
    echo "  step $i: residual_error=$error"
    sleep 0.1
done

# ── Write output files ────────────────────────────────────────────────────
# Any files in $EXP_OUT are auto-detected by run-finish
echo '{"residual_error": 0.04, "iterations_used": 847, "converged": true}' \
    > "$EXP_OUT/results.json"
echo "x,y,z" > "$EXP_OUT/solution.csv"
echo "1.0,2.0,3.0" >> "$EXP_OUT/solution.csv"

# ── Finish with metrics from file ─────────────────────────────────────────
exptrack run-finish "$EXP_ID" --metrics "$EXP_OUT/results.json"
echo ""
echo "Done! View with: exptrack show $EXP_ID"
