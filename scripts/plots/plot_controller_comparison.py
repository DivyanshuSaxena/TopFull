"""
Compare logs of different controllers
Args:
    log_files (List[str]): List of paths to the log dirs.
"""

import sys
import numpy as np
import matplotlib.pyplot as plt

from utils import *

# Check if the log files are provided.
if len(sys.argv) < 4:
    print(
        "Usage: python3 plot_controller_comparison.py <save_name> <log_dir1> <log_dir2>"
    )
    sys.exit(1)

save_name = sys.argv[1]
log_dirs = sys.argv[2:]
num_controllers = len(log_dirs)

type_names = ["User", "Recommend", "Search", "Reserve"]
num_types = len(type_names)

# To plot: workload, goodput of all controllers
workload = []
all_goodputs = []
all_latencies = []
all_violations = []

for _ in range(num_controllers):
    failed, goodput, violations, latencies = read_csv_files(
        log_dirs[_], [name.lower() for name in type_names]
    )

    # Controller workload is the sum of failed and goodput rates.
    controller_workload = np.add(failed, goodput)

    if len(workload) == 0:
        workload = controller_workload
    else:
        # Check if the workload is the same.
        diff = np.subtract(workload, controller_workload)

        # Get entries that are more than 20.
        diff_larger = np.abs(diff) > 20
        if np.any(diff_larger):
            print("Workload is different for the controllers.")

            # Print the entries that are more than 20.
            print(diff[np.where(diff_larger)])

    all_goodputs.append(goodput)
    all_latencies.append(latencies)
    all_violations.append([100 * violations[i] for i in range(num_types)])

# Plot the workload and goodputs.
plt.rcParams["font.size"] = 18

colors = ["#D5E8D4", "#FFE6CC", "#F8CECC", "#CDD9E9", "#F1E6C6", "#DBCFE1"]
edge_colors = ["#82B366", "#D79B00", "#B85450", "#6C8EBF", "#D6B656", "#9673A6"]
styles = ["-.", "--", "dotted", "-"]
markers = ["o", "P", "^", "s", "v", "^"]

controller_names = []
for i in range(num_controllers):
    # Extract controller name from the log_dir.
    run_name = log_dirs[i].split("/")[-1]
    if "galileo" in run_name:
        controller_name = "Galileo"
    elif "training" in run_name:
        controller_name = "TopFull Fine-tuned"
    else:
        controller_name = "TopFull Base"
    controller_names.append(controller_name)


fig = plt.figure(figsize=(8.4, 4.8))

# Plot the total workload.
plt.plot(workload, label="Applied Workload", color="black", linestyle=styles[0])

# Plot the goodputs of all controllers.
for i in range(num_controllers):
    # Print average goodput.
    print(f"Average goodput for {controller_names[i]}: {np.average(all_goodputs[i])}")
    plt.plot(
        all_goodputs[i],
        label=controller_names[i],
        linewidth=2,
        color=edge_colors[i],
        linestyle=styles[i + 1],
    )

plt.ylabel("Request Rate (rps)")
plt.xlabel("Time (min)")
plt.legend(loc="upper center", bbox_to_anchor=(0.5, 1.3), ncol=2, frameon=False)
plt.subplots_adjust(top=0.8, bottom=0.15, left=0.15, right=0.95)

plt.savefig(f"figures/goodput_{save_name}.png")
plt.close()

# Make another bar plot for the violations.
fig = plt.figure(figsize=(8.4, 4.8))

# Make a bar plot, with a set of bars for each request type.
xpos = np.arange(num_types) * num_controllers
for i in range(num_controllers):
    pos = [x + i * 0.8 for x in xpos]
    plt.bar(
        pos,
        all_violations[i],
        width=0.8,
        color=colors[i],
        edgecolor=edge_colors[i],
        linewidth=2,
        label=controller_names[i]
    )

plt.xticks([(p + 0.8 * (num_controllers - 1) / 2) for p in xpos], type_names)
plt.ylabel("SLO Violations (%age)")
plt.legend(loc="upper center", bbox_to_anchor=(0.45, 1.2), ncol=3, frameon=False)
plt.subplots_adjust(top=0.85, bottom=0.12, left=0.12, right=0.95)

plt.savefig(f"figures/violations_{save_name}.png")
plt.close()
