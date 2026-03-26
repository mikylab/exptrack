#!/bin/bash
#SBATCH --job-name=train_resnet
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gpus=1
#SBATCH --mem=32G
#SBATCH --time=04:00:00
#SBATCH --output=slurm-%j.out
#
# SLURM job script with expTrack integration.
#
# Submit with: sbatch examples/slurm_job.sh
#
# expTrack automatically captures SLURM_JOB_ID, SLURM_JOB_NAME,
# SLURM_NODELIST, etc. as parameters under the _slurm key.

set -euo pipefail

# ── Start tracking ────────────────────────────────────────────────────────
# eval $() captures the exported EXP_ID, EXP_NAME, EXP_OUT variables.
# --script is a naming hint; SLURM env vars are captured automatically.
eval $(exptrack run-start \
    --script train_resnet \
    --tags slurm gpu \
    --lr 0.001 \
    --batch-size 256 \
    --epochs 90 \
    --model resnet50)

echo "Experiment: $EXP_NAME ($EXP_ID)"
echo "Output dir: $EXP_OUT"

# ── Trap for clean failure reporting ──────────────────────────────────────
# If the job crashes or is killed, mark the experiment as failed.
cleanup() {
    exit_code=$?
    if [ $exit_code -ne 0 ]; then
        exptrack run-fail "$EXP_ID" "Exit code $exit_code"
    fi
}
trap cleanup EXIT

# ── Run training ──────────────────────────────────────────────────────────
# Your actual training command goes here. The script can be anything:
# Python, C++, Julia, R, or even another shell script.
python train.py \
    --lr 0.001 \
    --batch-size 256 \
    --epochs 90 \
    --model resnet50 \
    --output-dir "$EXP_OUT"

# ── Log metrics mid-run (optional) ───────────────────────────────────────
# If your training writes a metrics file, you can log it:
# exptrack log-metric $EXP_ID val_loss 0.234 --step 90
# Or log from a JSON file:
# exptrack log-metric $EXP_ID --file "$EXP_OUT/metrics.json" --step 90

# ── Link external directories (optional) ─────────────────────────────────
# If training writes to a separate directory (TensorBoard, checkpoints):
# exptrack link-dir $EXP_ID ./logs/tensorboard --label tensorboard
# exptrack link-dir $EXP_ID ./checkpoints --label checkpoints

# ── Log final results ────────────────────────────────────────────────────
# exptrack log-result stores final metrics with source=pipeline
if [ -f "$EXP_OUT/results.json" ]; then
    exptrack log-result $EXP_ID --file "$EXP_OUT/results.json" --source pipeline
fi

# ── Finish ────────────────────────────────────────────────────────────────
# --metrics loads a JSON file with final metrics.
# --params adds extra params discovered at runtime (e.g. best_epoch).
exptrack run-finish "$EXP_ID" \
    --metrics "$EXP_OUT/results.json"

echo "Done. View results: exptrack show $EXP_ID"
