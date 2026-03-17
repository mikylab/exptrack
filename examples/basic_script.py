# Run with: exptrack run basic_script.py --lr 0.01 --epochs 10 --batch-size 32
#
# This script has ZERO exptrack imports. expTrack automatically captures
# argparse parameters by monkey-patching parse_args() at runtime.
#
# When run via `exptrack run`, the __exptrack__ global is injected so you
# can optionally log metrics. The script also works standalone with plain
# `python basic_script.py` — the metric calls are just skipped.

import argparse
import random
import time

parser = argparse.ArgumentParser(description="Simulated training script")
parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")
parser.add_argument("--epochs", type=int, default=5, help="Number of epochs")
parser.add_argument("--batch-size", type=int, default=64, help="Batch size")
parser.add_argument("--model", type=str, default="mlp", help="Model type")
args = parser.parse_args()

# If running under exptrack, __exptrack__ is the active Experiment object.
# If running standalone, this is None and metric calls are skipped.
exp = globals().get("__exptrack__")

# Simulate a training loop
loss = 2.0
for epoch in range(1, args.epochs + 1):
    # Fake training: loss decreases with some noise
    loss *= (1 - args.lr)
    loss += random.uniform(-0.05, 0.05)
    acc = min(1.0, 0.5 + epoch * 0.08 + random.uniform(-0.02, 0.02))

    # Log metrics if running under exptrack
    if exp:
        exp.log_metric("loss", round(loss, 4), step=epoch)
        exp.log_metric("acc", round(acc, 4), step=epoch)

    print(f"Epoch {epoch}/{args.epochs}  loss={loss:.4f}  acc={acc:.4f}")
    time.sleep(0.1)  # Simulate work

print(f"\nTraining complete. Final loss: {loss:.4f}")
