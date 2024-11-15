#!/usr/bin/env bash
# 1: Name of the experiment
# 2: Start node of experiment
# 3: End node of experiment

NODE_PREFIX="node-"
EXP_NAME=$1
PROJECT_EXT="wisr-PG0"
DOMAIN="utah.cloudlab.us"
USER_NAME="dsaxena"
HOSTS=$(./cloudlab/nodes.sh $1 $2 $3)

# Run command on every node
for host in $HOSTS; do
  echo $host
  ssh -o StrictHostKeyChecking=no $host "/bin/bash -c 'cd \$HOME/out; rm -f *.run'"
done
