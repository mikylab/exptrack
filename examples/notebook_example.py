# Notebook workflow for expTrack (shown as .py for portability).
#
# In a real Jupyter notebook, you would either:
#   1. Use the magic:    %load_ext exptrack   (zero-friction, auto-captures)
#   2. Use explicit API: import exptrack.notebook as exp  (shown below)
#
# The magic approach patches cell execution automatically.
# The explicit API gives you fine-grained control.

import random

import exptrack.notebook as exp

# --- Cell 1: Start an experiment ---
exp.start(name="notebook-demo")
print("Experiment started")

# --- Cell 2: Log parameters ---
exp.param("model", "transformer")
exp.param("lr", 0.001)
exp.param("dropout", 0.1)

# --- Cell 3: Training loop with metrics ---
for epoch in range(1, 6):
    loss = 2.0 * (0.8 ** epoch) + random.uniform(-0.05, 0.05)
    exp.metric("loss", round(loss, 4), step=epoch)
    print(f"Epoch {epoch}: loss={loss:.4f}")

# --- Cell 4: Save an output and tag ---
path = exp.out("summary.txt")
with open(path, "w") as f:
    f.write("Training complete.\n")
exp.tag("demo")
exp.note("Ran from notebook_example.py")

# --- Cell 5: Finish ---
exp.done()
print("Experiment finished. View with: exptrack show <id>")
