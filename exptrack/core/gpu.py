"""
exptrack/core/gpu.py — GPU/CUDA state capture

Extracts GPU information from the environment and nvidia-smi
so experiments record which GPU(s) were available/used.
"""
from __future__ import annotations

import os
import subprocess
import sys


def gpu_info() -> dict[str, object]:
    """Capture GPU/CUDA information from the environment.

    Returns a dict with keys like:
      cuda_visible_devices  — value of CUDA_VISIBLE_DEVICES env var (or None)
      gpu_count             — number of visible GPUs (0 if none)
      gpu_devices           — list of GPU name strings from nvidia-smi
      gpu_memory_mb         — list of total memory per GPU in MB

    All operations are best-effort; failures silently return empty/zero values.
    """
    info: dict[str, object] = {}

    # 1. Capture CUDA_VISIBLE_DEVICES from environment
    cvd = os.environ.get("CUDA_VISIBLE_DEVICES")
    if cvd is not None:
        info["cuda_visible_devices"] = cvd

    # 2. Query nvidia-smi for GPU details
    devices, memory = _nvidia_smi_query()
    info["gpu_count"] = len(devices)
    if devices:
        info["gpu_devices"] = devices
    if memory:
        info["gpu_memory_mb"] = memory

    return info


def _nvidia_smi_query() -> tuple[list[str], list[int]]:
    """Run nvidia-smi to get GPU names and memory.

    Returns (device_names, memory_mb) lists.
    Returns empty lists on any failure (no GPU, nvidia-smi not found, etc.).
    """
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return [], []

        devices = []
        memory = []
        for line in r.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                devices.append(parts[0])
                try:
                    memory.append(int(float(parts[1])))
                except (ValueError, IndexError):
                    pass
            elif parts:
                devices.append(parts[0])

        # If CUDA_VISIBLE_DEVICES is set, filter to only visible GPUs
        cvd = os.environ.get("CUDA_VISIBLE_DEVICES")
        if cvd is not None and devices:
            try:
                indices = [int(i.strip()) for i in cvd.split(",") if i.strip()]
                devices = [devices[i] for i in indices if i < len(devices)]
                memory = [memory[i] for i in indices if i < len(memory)]
            except (ValueError, IndexError):
                pass  # non-numeric CVD values (e.g. GPU UUIDs) — keep all

        return devices, memory
    except FileNotFoundError:
        # nvidia-smi not installed
        return [], []
    except Exception as e:
        print(f"[exptrack] warning: nvidia-smi query failed: {e}", file=sys.stderr)
        return [], []
