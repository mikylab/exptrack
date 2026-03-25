#!/bin/bash
# Wrapper script that runs multiple scripts as stages in one study.
#
# Shows how EXP_STUDY and EXP_STAGE are automatically inherited by
# subsequent run-start calls, so you only need to set the study once.
#
# Run with: bash examples/pipeline_wrapper.sh

set -euo pipefail

# ── Trap for failure reporting ────────────────────────────────────────────
cleanup() {
    exit_code=$?
    if [ $exit_code -ne 0 ] && [ -n "${EXP_ID:-}" ]; then
        exptrack run-fail "$EXP_ID" "Wrapper exited with code $exit_code"
    fi
}
trap cleanup EXIT

# ── Stage 1: Preprocessing ───────────────────────────────────────────────
# First run-start sets the study and stage. EXP_STUDY and EXP_STAGE
# are exported so subsequent run-start calls inherit them.
eval $(exptrack run-start \
    --script preprocess \
    --study "pipeline-$(date +%s)" \
    --stage 1 --stage-name preprocess \
    --input-format csv \
    --normalize true)

echo "[stage 1] Preprocessing: $EXP_ID (study=$EXP_STUDY, stage=$EXP_STAGE)"
mkdir -p "$EXP_OUT"
echo "rows=5000" > "$EXP_OUT/data_stats.txt"
exptrack log-metric "$EXP_ID" input_rows 5000
exptrack run-finish "$EXP_ID"
echo ""

# ── Stage 2: Training ────────────────────────────────────────────────────
# No --study needed (inherited from EXP_STUDY).
# No --stage needed (auto-increments from EXP_STAGE: 1 → 2).
eval $(exptrack run-start \
    --script train \
    --stage-name train \
    --lr 0.001 --epochs 10 --batch-size 64)

echo "[stage 2] Training: $EXP_ID (study=$EXP_STUDY, stage=$EXP_STAGE)"
mkdir -p "$EXP_OUT"

# Simulate training with metrics
for epoch in 1 2 3 4 5; do
    loss=$(python3 -c "import random; print(round(2.0 * 0.8**$epoch + random.uniform(-0.05, 0.05), 4))")
    exptrack log-metric "$EXP_ID" loss "$loss" --step "$epoch"
    echo "  epoch $epoch: loss=$loss"
done

echo '{"best_loss": 0.42, "best_epoch": 4}' > "$EXP_OUT/results.json"
echo "model_weights" > "$EXP_OUT/model.pt"
exptrack run-finish "$EXP_ID" --metrics "$EXP_OUT/results.json"
echo ""

# ── Stage 3: Evaluation ──────────────────────────────────────────────────
# Still inherits study, stage auto-increments to 3.
eval $(exptrack run-start \
    --script evaluate \
    --stage-name evaluate)

echo "[stage 3] Evaluating: $EXP_ID (study=$EXP_STUDY, stage=$EXP_STAGE)"
mkdir -p "$EXP_OUT"
exptrack log-metric "$EXP_ID" test_accuracy 0.94
exptrack log-metric "$EXP_ID" test_f1 0.91
echo '{"accuracy": 0.94, "f1": 0.91, "precision": 0.93}' > "$EXP_OUT/eval_results.json"
exptrack run-finish "$EXP_ID" --metrics "$EXP_OUT/eval_results.json"
echo ""

# ── Summary ───────────────────────────────────────────────────────────────
echo "Pipeline complete!"
echo "View all stages: exptrack ls --study $EXP_STUDY"
echo "Dashboard:       exptrack ui"
