#!/usr/bin/env bash
# Run query for the Hotel Reservation benchmark
# Arguments:
# --init: whether first time install
# --stats: whether to start the stats server
# --client: whether to start the stats client
# --ip: IP address of the stats server

showHelp() {
cat << EOF  
Usage: <script_name> [-iscl] [-I <ip>] [-p <port>] [-r <rate>] [-t <type>]
Run query for the Hotel Reservation benchmark

-h, -help,      --help        Display help
-i, -init,      --init        Whether first time install
-c, -client,    --client      Whether to start the stats client
-l, -log,       --log         Whether to log the output
-I, -ip,        --ip          IP address of the stats server
-p, -port,      --port        Port of the application
-r, -rate,      --rate        Rate of requests per second
-t, -type,      --type        Type of the workload (search/user/reserve/mixed)

EOF
}

INIT=0
CLIENT=0
LOG=0
IP=""
TYPE="mixed"
RATE=2000
PORT=32000

options=$(getopt -l "help,init,client,log,type:,ip:,port:,rate:" -o "hiclt:I:p:r:" -a -- "$@")

eval set -- "$options"

while true; do
  case "$1" in
  -h|--help) 
      showHelp
      exit 0
      ;;
  -i|--init)
      INIT=1
      ;;
  -c|--client)
      CLIENT=1
      ;;
  -l|--log)
      LOG=1
      ;;
  -I|--ip)
      shift
      IP=$1
      ;;
  -p|--port)
      shift
      PORT=$1
      ;;
  -r|--rate)
      shift
      RATE=$1
      ;;
  -t|--type)
      shift
      TYPE=$1
      ;;
  --)
      shift
      break;;
  esac
  shift
done

: "${TESTBED:=$HOME}"
pushd $TESTBED

if [[ $INIT -eq 1 ]]; then
  sudo apt install -y luarocks
  sudo luarocks install luasocket

  # Pull docker image 
  docker pull divyanshus/hotelreservation

  if [ ! -d "$TESTBED/DeathStarBench" ]; then
    git clone https://github.com/DivyanshuSaxena/DeathStarBench.git

    # Make wrk2 executable
    pushd DeathStarBench
    git checkout topfull
    popd
  fi

  pushd DeathStarBench/hotelReservation
  kubectl apply -Rf kubernetes/
  popd

  # Wait for the pods to get running
  sleep 1m
fi

if [[ $CLIENT -eq 1 ]]; then
  GATEWAY_URL="$IP:$PORT"
  echo "Starting the test with GATEWAY_URL=$GATEWAY_URL"

  # Warm-up
  pushd DeathStarBench/hotelReservation
  ../wrk2/wrk -D exp -t 5 -c 5 -d 20 -L -s ./wrk2/scripts/hotel-reservation/mixed-workload_type_1.lua http://$GATEWAY_URL -R 10

  sleep 10

  # Run queries to log timings
  if [[ $LOG -eq 1 ]]; then
    echo "Logging the output to $TESTBED/out" 
    if [[ $TYPE == "search" ]]; then
      ../wrk2/wrk -D exp -t 10 -c 10 -d 60000 -L -s ./wrk2/scripts/hotel-reservation/search-workload.lua http://$GATEWAY_URL -R $RATE >> $TESTBED/out/time_res_search_${RATE}.run 2>&1
    elif [[ $TYPE == "user" ]]; then
      ../wrk2/wrk -D exp -t 10 -c 10 -d 60000 -L -s ./wrk2/scripts/hotel-reservation/user-workload.lua http://$GATEWAY_URL -R $RATE >> $TESTBED/out/time_res_user_${RATE}.run 2>&1
    elif [[ $TYPE == "reserve" ]]; then
      ../wrk2/wrk -D exp -t 10 -c 10 -d 60000 -L -s ./wrk2/scripts/hotel-reservation/reserve-workload.lua http://$GATEWAY_URL -R $RATE >> $TESTBED/out/time_res_reserve_${RATE}.run 2>&1
    elif [[ $TYPE == "recommend" ]]; then
      ../wrk2/wrk -D exp -t 10 -c 10 -d 60000 -L -s ./wrk2/scripts/hotel-reservation/recommend-workload.lua http://$GATEWAY_URL -R $RATE >> $TESTBED/out/time_res_recommend_${RATE}.run 2>&1
    else
      ../wrk2/wrk -D exp -t 10 -c 10 -d 60000 -L -s ./wrk2/scripts/hotel-reservation/mixed-workload_type_1.lua http://$GATEWAY_URL -R $RATE >> $TESTBED/out/time_reservation_${RATE}.run 2>&1
    fi
  else
    if [[ $TYPE == "search" ]]; then
      ../wrk2/wrk -D exp -t 10 -c 10 -d 60000 -L -s ./wrk2/scripts/hotel-reservation/search-workload.lua http://$GATEWAY_URL -R $RATE
    elif [[ $TYPE == "user" ]]; then
      ../wrk2/wrk -D exp -t 10 -c 10 -d 60000 -L -s ./wrk2/scripts/hotel-reservation/user-workload.lua http://$GATEWAY_URL -R $RATE
    elif [[ $TYPE == "reserve" ]]; then
      ../wrk2/wrk -D exp -t 10 -c 10 -d 60000 -L -s ./wrk2/scripts/hotel-reservation/reserve-workload.lua http://$GATEWAY_URL -R $RATE
    elif [[ $TYPE == "recommend" ]]; then
      ../wrk2/wrk -D exp -t 10 -c 10 -d 60000 -L -s ./wrk2/scripts/hotel-reservation/recommend-workload.lua http://$GATEWAY_URL -R $RATE
    else
      ../wrk2/wrk -D exp -t 10 -c 10 -d 60000 -L -s ./wrk2/scripts/hotel-reservation/mixed-workload_type_1.lua http://$GATEWAY_URL -R $RATE
    fi
  fi

fi

popd
