"""
Resume training example for exptrack.

Shows how exptrack auto-detects --resume from the script's args and
continues the same experiment instead of creating a new one.

First run (creates a new experiment):
    exptrack run examples/resume_training.py --output_dir /tmp/exp_results --epochs 5

Resume (continues the same experiment — metrics aggregate):
    exptrack run examples/resume_training.py --output_dir /tmp/exp_results --epochs 10 --resume
"""
import argparse
import json
import os
import random

parser = argparse.ArgumentParser()
parser.add_argument("--lr", type=float, default=0.01)
parser.add_argument("--epochs", type=int, default=5)
parser.add_argument("--output_dir", default="/tmp/exp_results")
parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
args = parser.parse_args()

os.makedirs(args.output_dir, exist_ok=True)

# Get the experiment handle (injected by exptrack run)
exp = globals().get("__exptrack__")

# Load previous state if resuming
state_file = os.path.join(args.output_dir, "state.json")
start_epoch = 0
loss = 2.0

if args.resume and os.path.exists(state_file):
    with open(state_file) as f:
        state = json.load(f)
    start_epoch = state["epoch"]
    loss = state["loss"]
    print(f"Resuming from epoch {start_epoch}, loss={loss:.4f}")
else:
    print("Starting fresh")

# Training loop
for epoch in range(start_epoch, args.epochs):
    loss = loss * 0.85 + random.uniform(-0.02, 0.02)
    acc = 1.0 - loss * 0.3 + random.uniform(-0.01, 0.01)

    if exp:
        exp.log_metrics({"loss": loss, "accuracy": acc}, step=epoch)

    print(f"Epoch {epoch}: loss={loss:.4f}, acc={acc:.4f}")

    # Save checkpoint
    with open(state_file, "w") as f:
        json.dump({"epoch": epoch + 1, "loss": loss, "lr": args.lr}, f)

print(f"Done. Results in {args.output_dir}")
