#!/bin/bash
# Multi-step pipeline example for expTrack.
#
# Shows how to track separate experiments for each stage of a pipeline
# (train → test → analyze) and group them in a study with numbered stages.
#
# Run with: bash examples/pipeline_multistep.sh

set -e

# Study name groups all steps in this pipeline run
STUDY="pipeline-$(date +%s)"
echo "Study: $STUDY"
echo ""

# ── Step 1: Training ────────────────────────────────────────────────────────
eval $(exptrack run-start --script train --study "$STUDY" --stage 1 --stage-name train \
      --lr 0.01 --epochs 5)
TRAIN_ID=$EXP_ID
TRAIN_OUT=$EXP_OUT
echo "[stage 1/3] Training: $TRAIN_ID"

# Simulate training with metrics
for epoch in 1 2 3 4 5; do
    loss=$(python3 -c "import random; print(round(2.0 * 0.8**$epoch + random.uniform(-0.05, 0.05), 4))")
    acc=$(python3 -c "import random; print(round(0.5 + 0.1*$epoch + random.uniform(-0.02, 0.02), 4))")
    exptrack log-metric $TRAIN_ID train_loss $loss --step $epoch
    exptrack log-metric $TRAIN_ID train_acc $acc --step $epoch
    echo "  epoch $epoch: loss=$loss acc=$acc"
done

# Save a model checkpoint as artifact
echo "model_weights_placeholder" > "$TRAIN_OUT/model.pt"
exptrack run-finish $TRAIN_ID
echo ""

# ── Step 2: Testing ─────────────────────────────────────────────────────────
eval $(exptrack run-start --script test --study "$STUDY" --stage 2 --stage-name test \
      --model "$TRAIN_OUT/model.pt")
TEST_ID=$EXP_ID
echo "[stage 2/3] Testing: $TEST_ID"

# Simulate test metrics
exptrack log-metric $TEST_ID test_acc 0.94
exptrack log-metric $TEST_ID test_f1 0.91
exptrack log-metric $TEST_ID test_loss 0.187

# Save predictions
echo "pred1,0.95" > "$EXP_OUT/predictions.csv"
echo "pred2,0.87" >> "$EXP_OUT/predictions.csv"
exptrack run-finish $TEST_ID
echo ""

# ── Step 3: Analysis ────────────────────────────────────────────────────────
eval $(exptrack run-start --script analyze --study "$STUDY" --stage 3 --stage-name analyze)
ANALYZE_ID=$EXP_ID
echo "[stage 3/3] Analyzing: $ANALYZE_ID"

# Simulate generating a report
echo "Analysis complete. Model accuracy: 0.94, F1: 0.91" > "$EXP_OUT/report.txt"
exptrack log-artifact $ANALYZE_ID "$EXP_OUT/report.txt" --label "analysis report"
exptrack run-finish $ANALYZE_ID
echo ""

# ── Summary ─────────────────────────────────────────────────────────────────
echo "Pipeline complete!"
echo "  Train:   exptrack show $TRAIN_ID"
echo "  Test:    exptrack show $TEST_ID"
echo "  Analyze: exptrack show $ANALYZE_ID"
echo ""
echo "View all steps together:"
echo "  exptrack ls --study $STUDY"
echo "  exptrack studies"
echo "  exptrack ui               # open dashboard, filter by study"
