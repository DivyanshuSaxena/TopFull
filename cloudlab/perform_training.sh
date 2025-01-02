#!/usr/bin/env bash
# $1: Name of the experiment
# $2: Training type (galileo/topfull)
# $3: application (reservation/social)
# $4: workload
# $5: delta (change in environment)
# $6: eta (regulate weight of certificate cost)
# $7: results directory

# Check if there are at least 7 arguments
if [[ $# -lt 7 ]]; then
  echo "Usage: $0 <experiment_name> <experiment_type> <application> <workload> <delta> <eta> <results_dir>"
  exit 1
fi

EXP_NAME=$1
EXP_TYPE=$2
APP=$3
WORKLOAD=$4

# NOTE: For TopFull training, we currently do not use the values of DELTA and ETA.
DELTA=$5
ETA=$6

mapfile -t HOSTS < <(./cloudlab/nodes.sh ${EXP_NAME} 0 4 --all)

CONTROL_NODE=${HOSTS[0]}
CLIENT_NODE=${HOSTS[4]}

# Whether to use certificates when training
USE_CERTIFICATES=0
if [[ $EXP_TYPE == *"galileo"* ]]; then
  USE_CERTIFICATES=1
fi

REWARD_TYPE=""
if [[ $EXP_TYPE == *"sigmoid"* ]]; then
  REWARD_TYPE="sigmoid"
fi

# Results directory depends on the experiment type
RESULTS_DIR=${APP}/training-${EXP_TYPE}-$(date +%d%m-%H%M)
LOCAL_RESULTS_DIR=$7/${RESULTS_DIR}
CLOUDLAB_RESULTS_DIR=/proj/wisr-PG0/galileo-adm/${RESULTS_DIR}

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
  python3 transfer_learning.py ${APP} 5 ${USE_CERTIFICATES} ${REWARD_TYPE} > \$HOME/out/transfer.out 2>&1
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
  python3 execute_workload.py ~/out/ locust_reservation.py http://10.10.1.1:32000 10 1 ${WORKLOAD} 1 > ~/out/workload.out 2>&1
\""

sleep 5

ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux new-session -d -s metrics \"
  cd \$HOME/TopFull_master/online_boutique_scripts/src &&
  export GLOBAL_CONFIG_PATH=~/TopFull_master/online_boutique_scripts/src/global_config_reservation.json &&
  python3 metric_collector.py > \$HOME/out/metrics.out 2>&1
\""

# Sleep for an hour.
echo "Sleeping for 8 hours - 2 hours for training of each request type."
sleep 8h

# Check if any of the tmux sessions are still running - and close them.
echo "Killing control node tmus sessions and any topfull processes."
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux kill-session -t metrics"
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "ps aux | grep metric_collector | awk '{print \$2}' | xargs kill -9"

ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux kill-session -t rl"
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "ps aux | grep transfer_learning | awk '{print \$2}' | xargs kill -9"

ssh -o StrictHostKeyChecking=no $CONTROL_NODE "tmux kill-session -t proxy"
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "ps aux | grep proxy_hotel_reservation | awk '{print \$2}' | xargs kill -9"

# Check if the workload is still running
WORKLOAD_STATUS=$(ssh -o StrictHostKeyChecking=no $CLIENT_NODE "tmux list-sessions | grep workload")
if [[ -n $WORKLOAD_STATUS ]]; then
  echo "Workload is still running. Killing it and any execute_workload processes."
  ssh -o StrictHostKeyChecking=no $CLIENT_NODE "tmux kill-session -t workload"
  ssh -o StrictHostKeyChecking=no $CLIENT_NODE "ps aux | grep execute | awk '{print \$2}' | xargs kill -9"
fi

# Get training logs from the control node.
echo "Getting logs from the control node"
mkdir -p ${LOCAL_RESULTS_DIR}
pushd ${LOCAL_RESULTS_DIR}
scp -o StrictHostKeyChecking=no $CONTROL_NODE:~/TopFull_master/online_boutique_scripts/src/logs/* .

# Also get all the out/* files from the control node and the client node.
scp -o StrictHostKeyChecking=no $CONTROL_NODE:~/out/* .
scp -o StrictHostKeyChecking=no $CLIENT_NODE:~/out/* .

# Get the trained models.
echo "Getting the trained models from the control node"
scp -r -o StrictHostKeyChecking=no "$CONTROL_NODE:~/TopFull_master/online_boutique_scripts/src/training/*${APP}*" .
popd

# Move the trained model to the cloudlab results directory
echo "Moving the trained model to the cloudlab results directory"
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "mkdir -p ${CLOUDLAB_RESULTS_DIR}"
ssh -o StrictHostKeyChecking=no $CONTROL_NODE "cp -r ~/TopFull_master/online_boutique_scripts/src/training/*${APP}* ${CLOUDLAB_RESULTS_DIR}/"