# Run with: exptrack run basic_script.py --lr 0.01 --epochs 10 --batch-size 32
#
# This script has ZERO exptrack imports. expTrack automatically captures
# argparse parameters by monkey-patching parse_args() at runtime.

import argparse
import random
import time

parser = argparse.ArgumentParser(description="Simulated training script")
parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")
parser.add_argument("--epochs", type=int, default=5, help="Number of epochs")
parser.add_argument("--batch-size", type=int, default=64, help="Batch size")
parser.add_argument("--model", type=str, default="mlp", help="Model type")
args = parser.parse_args()

# Simulate a training loop
loss = 2.0
for epoch in range(1, args.epochs + 1):
    # Fake training: loss decreases with some noise
    loss *= (1 - args.lr)
    loss += random.uniform(-0.05, 0.05)
    acc = min(1.0, 0.5 + epoch * 0.08 + random.uniform(-0.02, 0.02))

    print(f"Epoch {epoch}/{args.epochs}  loss={loss:.4f}  acc={acc:.4f}")
    time.sleep(0.1)  # Simulate work

print(f"\nTraining complete. Final loss: {loss:.4f}")
