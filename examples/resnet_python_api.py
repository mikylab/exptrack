# Run with: python resnet_python_api.py
#
# Same ResNet training as resnet_exptrack_run.py, but using the explicit
# Python API. You manage the full experiment lifecycle: create it, log
# params, log metrics, finish it.
#
# Use this approach when:
#   - You want full control over experiment creation and naming
#   - You need to register artifacts manually
#   - You're building exptrack into a custom training framework
#
# Requires exptrack installed (`pip install -e .`).

import argparse
import random
import time

from exptrack.core import Experiment

parser = argparse.ArgumentParser(description="ResNet training (simulated)")
parser.add_argument("--lr", type=float, default=0.1, help="Learning rate")
parser.add_argument("--epochs", type=int, default=90, help="Number of epochs")
parser.add_argument("--batch-size", type=int, default=128, help="Batch size")
parser.add_argument("--optimizer", type=str, default="sgd", help="Optimizer")
parser.add_argument("--weight-decay", type=float, default=1e-4, help="Weight decay")
args = parser.parse_args()

# With the Python API, you log params yourself (exptrack run does this automatically)
with Experiment(name="resnet50", params=vars(args)) as exp:
    exp.add_tag("resnet")
    exp.add_note("ResNet-50 training with SGD")

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

        # Log multiple metrics per epoch
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

    # Log a final standalone metric
    exp.log_metric("best_val_acc", round(best_val_acc, 4))

    # Save a results file as an artifact
    out_path = exp.save_output("results.txt")
    with open(out_path, "w") as f:
        f.write(f"best_val_acc={best_val_acc:.4f}\n")
        f.write(f"final_train_loss={train_loss:.4f}\n")

    print(f"\nExperiment {exp.id} complete. Best val accuracy: {best_val_acc:.4f}")
    print(f"Results saved to: {out_path}")
