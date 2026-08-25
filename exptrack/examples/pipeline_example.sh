#!/bin/bash
# Shell pipeline integration for expTrack.
# Useful for SLURM jobs, CI pipelines, or multi-step workflows.
#
# Run with: bash examples/pipeline_example.sh

set -e

# Start a run — eval captures the exported EXP_ID variable
eval $(exptrack run-start --lr 0.01 --epochs 20 --model resnet18)
echo "Started experiment: $EXP_ID"

# Simulate training steps and log metrics
for epoch in 1 2 3 4 5; do
    loss=$(python3 -c "import random; print(round(2.0 * 0.8**$epoch + random.uniform(-0.05, 0.05), 4))")
    exptrack log-metric $EXP_ID loss $loss --step $epoch
    echo "Epoch $epoch: loss=$loss"
done

# Save a results file and register it as an artifact
echo "training_complete=true" > /tmp/results_${EXP_ID}.txt
exptrack log-artifact $EXP_ID /tmp/results_${EXP_ID}.txt --label results

# Write final metrics to a file, then finish the run
echo '{"final_loss": 0.42}' > /tmp/metrics_${EXP_ID}.json
exptrack run-finish $EXP_ID --metrics /tmp/metrics_${EXP_ID}.json
echo "Experiment $EXP_ID finished. View with: exptrack show $EXP_ID"
