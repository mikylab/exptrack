# Run with: python manual_tracking.py
#
# Shows the explicit Python API using the Experiment class directly.
# Use this when you want full control over what gets tracked.

import random

from exptrack.core import Experiment

# Experiment as a context manager — auto-finishes on exit
with Experiment() as exp:
    # Log hyperparameters
    exp.log_param("lr", 0.01)
    exp.log_param("optimizer", "sgd")
    exp.log_param("hidden_dim", 128)

    # Tag and annotate the run
    exp.add_tag("baseline")
    exp.add_tag("v2")
    exp.add_note("Testing SGD with small learning rate")

    # Simulate training and log metrics at each step
    loss = 3.0
    for step in range(1, 21):
        loss *= 0.92
        loss += random.uniform(-0.05, 0.05)
        exp.log_metric("loss", round(loss, 4), step=step)
        exp.log_metric("acc", round(min(1.0, 0.4 + step * 0.03), 4), step=step)

    # Save an output file as an artifact
    out_path = exp.save_output("results.txt")
    with open(out_path, "w") as f:
        f.write(f"final_loss={loss:.4f}\n")

    print(f"Experiment {exp.id} complete.")
    print(f"Output saved to: {out_path}")
