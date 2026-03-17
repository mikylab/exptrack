#!/bin/bash
# Multi-step pipeline example for expTrack.
#
# Shows how to track separate experiments for each stage of a pipeline
# (train → test → analyze) and group them with a shared tag.
#
# Run with: bash examples/pipeline_multistep.sh

set -e

# Shared tag to group all steps in this pipeline run
RUN_TAG="pipeline-$(date +%s)"
echo "Pipeline tag: $RUN_TAG"
echo ""

# ── Step 1: Training ────────────────────────────────────────────────────────
eval $(exptrack run-start --script train --phase train --lr 0.01 --epochs 5 --tag "$RUN_TAG")
TRAIN_ID=$EXP_ID
TRAIN_OUT=$EXP_OUT
echo "[step 1/3] Training: $TRAIN_ID"

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
eval $(exptrack run-start --script test --phase test --model "$TRAIN_OUT/model.pt" --tag "$RUN_TAG")
TEST_ID=$EXP_ID
echo "[step 2/3] Testing: $TEST_ID"

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
eval $(exptrack run-start --script analyze --phase analyze --tag "$RUN_TAG")
ANALYZE_ID=$EXP_ID
echo "[step 3/3] Analyzing: $ANALYZE_ID"

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
echo "  exptrack ls               # filter by tag '$RUN_TAG' in dashboard"
echo "  exptrack ui               # open dashboard, filter by tag"
