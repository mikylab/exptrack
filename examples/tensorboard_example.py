# Run with: exptrack run tensorboard_example.py --lr 0.01 --epochs 15
#
# Requires a TensorBoard writer:  pip install tensorboardX   (or install torch)
#
# This script has ZERO exptrack imports and never calls log_metric().
# It only logs scalars to a normal TensorBoard SummaryWriter, exactly as a
# real training script would. When run via `exptrack run`, exptrack patches
# SummaryWriter at the call site and MIRRORS every scalar into its own metrics
# table — so the losses show up in `exptrack show` / the dashboard with no
# code changes.
#
# TensorBoard itself is unaffected: the original add_scalar() still runs and
# still writes the ./runs/ event files, so `tensorboard --logdir runs` works
# exactly as before. exptrack is a tee, not a replacement.
#
# After running, compare:
#   exptrack ls                     # the run is listed
#   exptrack show <id>              # loss / acc / lr_schedule appear as metrics
#   tensorboard --logdir runs       # the same scalars in TensorBoard

import argparse
import math
import random
import time

# The SummaryWriter is the ONLY logging exptrack needs — no exptrack import.
try:
    from torch.utils.tensorboard import SummaryWriter
except ImportError:
    try:
        from tensorboardX import SummaryWriter
    except ImportError:
        raise SystemExit(  # noqa: B904 — a user-facing hint, not error chaining
            "This demo needs a TensorBoard writer.\n"
            "  pip install tensorboardX   (lightweight)   — or install torch\n"
            "Then: exptrack run tensorboard_example.py --lr 0.01 --epochs 15"
        )

parser = argparse.ArgumentParser(description="TensorBoard auto-capture demo")
parser.add_argument("--lr", type=float, default=0.01, help="Learning rate")
parser.add_argument("--epochs", type=int, default=15, help="Number of epochs")
parser.add_argument("--batch-size", type=int, default=64, help="Batch size")
args = parser.parse_args()

writer = SummaryWriter()  # writes to ./runs/<timestamp> by default

loss = 2.0
for epoch in range(1, args.epochs + 1):
    # Fake training: loss decays, accuracy climbs, LR follows a cosine schedule.
    loss *= (1 - args.lr)
    loss += random.uniform(-0.03, 0.03)
    acc = min(1.0, 0.5 + epoch * 0.03 + random.uniform(-0.01, 0.01))
    lr_now = args.lr * 0.5 * (1 + math.cos(math.pi * epoch / args.epochs))

    # Plain TensorBoard logging — this is all exptrack intercepts.
    writer.add_scalar("loss", loss, epoch)                 # -> metric "loss"
    writer.add_scalar("acc", acc, epoch)                   # -> metric "acc"
    writer.add_scalars("schedule", {"lr": lr_now}, epoch)  # -> metric "schedule/lr"

    print(f"Epoch {epoch}/{args.epochs}  loss={loss:.4f}  acc={acc:.4f}  lr={lr_now:.5f}")
    time.sleep(0.05)

writer.close()
print("\nDone. Try:  exptrack ls   then   exptrack show <id>")
