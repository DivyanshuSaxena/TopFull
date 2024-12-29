"""
Read the controller logs and plot the latencies and observed goodput.
Args:
    log_file (str): Path to the log file.
"""

import os
import sys
import json
import numpy as np
import matplotlib.pyplot as plt

from utils import *

# Check if the log file is provided.
if len(sys.argv) < 2:
    print("Usage: python3 plot_controller_log.py <log_dir>")
    sys.exit(1)

log_dir = sys.argv[1]


type_names = ["User", "Recommend", "Search", "Reserve"]
num_types = len(type_names)

# Read the logs from the logs directory.
failed, goodput, violations, latencies = read_csv_files(log_dir, [name.lower() for name in type_names])

plt.rcParams['font.size'] = 18

# Plot the failed and goodput rates.
fig, axes = plt.subplots(2, 1, figsize=(12, 8))

# Plot the total failed and goodputs.
axes[0].plot(failed, label="Failed", linestyle='dashed')
axes[0].plot(goodput, label="Goodput", linewidth=2)
axes[0].minorticks_on()
axes[0].grid(which='major', linestyle='-', linewidth='0.5', color='black')
axes[0].grid(which='minor', linestyle=':', linewidth='0.5', color='black')
axes[0].legend()
axes[0].set_ylabel("Rate")
axes[0].set_xlabel("Time (min)")

# Print average goodput.
print(f"Average goodput: {np.average(goodput)}")

# Plot the latencies.
for i in range(num_types):
    axes[1].plot(latencies[i], label=f"99p {type_names[i]}", linewidth=2)
axes[1].axhline(y=100, color='r', linestyle='dashed')
axes[1].legend()
axes[1].set_ylabel("99p Latency")
axes[1].set_xlabel("Time (min)")

title_name = log_dir.split("/")[-1]
# figure.suptitle(f"Controller logs from {title_name}")

# plt.show()
plt.tight_layout()
# plt.subplots_adjust(top=0.9, bottom=0.12, left=0.07, right=0.98, hspace=0.6, wspace=0.75)

plt.savefig("figures/controller_log.png")