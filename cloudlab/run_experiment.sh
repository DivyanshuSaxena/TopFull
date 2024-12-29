#!/usr/bin/env bash
# $1: Name of the experiment
# $2: Experiment type (galileo/...)
# $3: application (reservation/social)
# $4: workload
# $5: results directory
# $6: checkpoint to use - Optional (if not provided, use the base checkpoint)
# $7: if stress (stress/nostress) - Optional

# Check if there are at least 5 arguments
if [[ $# -lt 5 ]]; then
  echo "Usage: $0 <experiment_name> <experiment_type> <application> <workload> <results_dir> [<checkpoint-path>] [<if_stress>]"
  exit 1
fi

EXP_NAME=$1
EXP_TYPE=$2
APP=$3
WORKLOAD=$4
CHECKPOINT_PATH=${6:-""}
IF_STRESS=${7:-"nostress"}

# If CHECKPOINT_PATH is not "", split by '/' and get the third last element.
if [[ $CHECKPOINT_PATH != "" ]]; then
  CHECKPOINT=$(echo $CHECKPOINT_PATH | tr "/" "\n" | tail -3 | head -1)
else
  CHECKPOINT="base"
fi

RESULTS_DIR=${APP}/${EXP_TYPE}-${WORKLOAD}-${IF_STRESS}-$(date +%d%m-%H%M)
LOCAL_RESULTS_DIR=$5/${RESULTS_DIR}-${CHECKPOINT}
CLOUDLAB_RESULTS_DIR=/proj/wisr-PG0/galileo/${RESULTS_DIR}-${CHECKPOINT}

mapfile -t HOSTS < <(./cloudlab/nodes.sh ${EXP_NAME} 0 4 --all)

CONTROL_NODE=${HOSTS[0]}
CLIENT_NODE=${HOSTS[4]}

# Start tmux sessions on the control node - one for the proxy, another for rl, and third for metrics collection.
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux new-session -d -s proxy \"
  cd \$HOME/TopFull_master/online_boutique_scripts/src/proxy &&
  export PATH=\$PATH:/usr/local/go/bin &&
  export GLOBAL_CONFIG_PATH=~/TopFull_master/online_boutique_scripts/src/global_config_reservation.json &&
  go run proxy_hotel_reservation.go > \$HOME/out/proxy.out 2>&1
\""

sleep 5

ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux new-session -d -s rl \"
  cd \$HOME/TopFull_master/online_boutique_scripts/src &&
  export GLOBAL_CONFIG_PATH=~/TopFull_master/online_boutique_scripts/src/global_config_reservation.json &&
  python3 deploy_rl.py ${CHECKPOINT_PATH} > \$HOME/out/rl.out 2>&1
\""

sleep 5

ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux new-session -d -s metrics \"
  cd \$HOME/TopFull_master/online_boutique_scripts/src &&
  export GLOBAL_CONFIG_PATH=~/TopFull_master/online_boutique_scripts/src/global_config_reservation.json &&
  python3 metric_collector.py > \$HOME/out/metrics.out 2>&1
\""

# Run the workload on the client node
echo "Running the workload on client node $CLIENT_NODE"

# If the WORKLOAD has rps in it, then use the traces file, else simply use the WORKLOAD variable.
if [[ $WORKLOAD == *"rps"* ]]; then
  echo "Using traces file for workload"
  WORKLOAD="~/scripts/deployment/traces/${WORKLOAD}.txt"
else
  echo "Using a fixed workload"
fi

# Start tmux session on the client node -- for workload generation.
ssh -o StrictHostKeyChecking=no $CLIENT_NODE "tmux new-session -d -s workload \"
  export PATH=\$HOME/.local/bin:\$PATH &&
  cd \$HOME/TopFull_loadgen &&
  python3 execute_workload.py ~/out/ locust_reservation.py http://10.10.1.1:32000 10 1 ${WORKLOAD} > ~/out/workload.out 2>&1
\""

# Sleep for an hour.
echo "Sleeping for an hour"
sleep 3660

# TODO: Currently we do not start the CPU stress process.
if [[ $IF_STRESS == "stress" ]]; then
  echo "Kill cpu stress on all nodes"
  for host in "${HOSTS[@]:0:4}" ; do
    echo "Kill the CPU stress processes on $host"
    ssh -o StrictHostKeyChecking=no $host "tmux kill-session -t cpu_monitor"
    ssh -o StrictHostKeyChecking=no $host "tmux kill-session -t cpu_bg"
  done
fi

# Check if any of the tmux sessions are still running - and close them.
echo "Killing control node tmus sessions and any topfull processes."
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux kill-session -t metrics"
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "ps aux | grep metric_collector | awk '{print \$2}' | xargs kill -9"

ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux kill-session -t rl"
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "ps aux | grep deploy_rl | awk '{print \$2}' | xargs kill -9"

ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux kill-session -t proxy"
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "ps aux | grep proxy_hotel_reservation | awk '{print \$2}' | xargs kill -9"

# Check if the workload is still running
WORKLOAD_STATUS=$(ssh -o StrictHostKeyChecking=no $CLIENT_NODE "tmux list-sessions | grep workload")
if [[ -n $WORKLOAD_STATUS ]]; then
  echo "Workload is still running. Killing it and any execute_workload processes."
  ssh -o StrictHostKeyChecking=no $CLIENT_NODE "tmux kill-session -t workload"
  ssh -o StrictHostKeyChecking=no $CLIENT_NODE "ps aux | grep execute | awk '{print \$2}' | xargs kill -9"
fi

# TODO: Currently we do not get the CPU usage logs.
if [[ $IF_STRESS == "stress" ]]; then
  # Get the CPU usage logs from the nodes
  index=0
  for host in "${HOSTS[@]:0:4}" ; do 
    echo "Copying CSV file from $host to cpu_$index.csv"
    scp -o StrictHostKeyChecking=no "$host:~/bg_stress/*.csv" "./cpu_$index.csv"
    ((index++))
  done
fi

# Get logs from the control node.
echo "Getting logs from the control node"
mkdir -p ${LOCAL_RESULTS_DIR}
pushd ${LOCAL_RESULTS_DIR}
scp -o StrictHostKeyChecking=no $CONTROL_NODE:~/TopFull_master/online_boutique_scripts/src/logs/* .

# Also get all the out/* files from the control node and the client node.
scp -o StrictHostKeyChecking=no $CONTROL_NODE:~/out/* .
scp -o StrictHostKeyChecking=no $CLIENT_NODE:~/out/* .
popd