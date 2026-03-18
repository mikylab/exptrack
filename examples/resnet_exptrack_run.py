# Run with: exptrack run resnet_exptrack_run.py --lr 0.1 --epochs 90 --batch-size 128
#
# ResNet training with zero exptrack imports. Parameters are captured
# automatically from argparse. Metrics are logged via the __exptrack__
# global — a single variable injected into the script's namespace by
# `exptrack run`. It does NOT pollute builtins or other modules; it only
# exists in this script's globals while running under exptrack.
#
# This script works fine with plain `python resnet_exptrack_run.py` too —
# metrics logging is simply skipped.

import argparse
import random
import time

parser = argparse.ArgumentParser(description="ResNet training (simulated)")
parser.add_argument("--lr", type=float, default=0.1, help="Learning rate")
parser.add_argument("--epochs", type=int, default=90, help="Number of epochs")
parser.add_argument("--batch-size", type=int, default=128, help="Batch size")
parser.add_argument("--optimizer", type=str, default="sgd", help="Optimizer")
parser.add_argument("--weight-decay", type=float, default=1e-4, help="Weight decay")
args = parser.parse_args()

# One line to get the experiment object. Returns None if not under exptrack run.
# This uses runpy.run_path(init_globals=...) under the hood — it's a fresh
# namespace for your script, not a modification of builtins or sys.modules.
exp = globals().get("__exptrack__")

# Simulate ResNet training
train_loss = 6.9
val_loss = 7.0
best_val_acc = 0.0

for epoch in range(1, args.epochs + 1):
    # Simulate training step
    train_loss *= (1 - args.lr * 0.01)
    train_loss += random.uniform(-0.05, 0.05)
    train_acc = min(1.0, 0.1 + epoch * 0.01 + random.uniform(-0.01, 0.01))

    # Simulate validation step
    val_loss *= (1 - args.lr * 0.008)
    val_loss += random.uniform(-0.03, 0.03)
    val_acc = min(1.0, 0.08 + epoch * 0.0095 + random.uniform(-0.01, 0.01))
    best_val_acc = max(best_val_acc, val_acc)

    # Log multiple metrics per epoch — all get the same step number
    if exp:
        exp.log_metrics({
            "train_loss": round(train_loss, 4),
            "train_acc": round(train_acc, 4),
            "val_loss": round(val_loss, 4),
            "val_acc": round(val_acc, 4),
        }, step=epoch)

    if epoch % 10 == 0 or epoch == 1:
        print(f"Epoch {epoch:3d}/{args.epochs}  "
              f"train_loss={train_loss:.4f}  train_acc={train_acc:.4f}  "
              f"val_loss={val_loss:.4f}  val_acc={val_acc:.4f}")

    time.sleep(0.02)

# Log a final standalone metric (no step — just the final value)
if exp:
    exp.log_metric("best_val_acc", round(best_val_acc, 4))

print(f"\nTraining complete. Best val accuracy: {best_val_acc:.4f}")
