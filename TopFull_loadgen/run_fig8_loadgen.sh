#!/bin/bash
GETPRODUCT=1500
POSTCHECKOUT=500
GETCART=200
POSTCART=200
CART=600
RATE=200

tmux kill-session -t session2
tmux new-session -d -s session2


tmux new-window -d -t session2 "locust -f locust_online_boutique.py --host=http://10.8.0.4:30440 --tags postcheckout --master-bind-port=8881  --master --expect-workers=10 --headless -u $POSTCHECKOUT -r $((POSTCHECKOUT / RATE)) -t 6m  < ports/8886"
for i in $(seq 1 10)
do
    tmux new-window -d -t session2 "locust -f locust_online_boutique.py --host=http://10.8.0.4:30440 --tags postcheckout --worker --master-port=8881  --master-host=127.0.0.1 < ports/$((i+8907))"
done



tmux kill-session -t session1
tmux new-session -d -s session1


tmux new-window -d -t session1 "locust -f locust_online_boutique.py --host=http://10.8.0.4:30440 --tags getproduct --master-bind-port=8882  --master --expect-workers=20 --headless -u $GETPRODUCT -r $((GETPRODUCT / RATE)) -t 6m  < ports/8887"
for i in $(seq 1 20)
do
    tmux new-window -d -t session1 "locust -f locust_online_boutique.py --host=http://10.8.0.4:30440 --tags getproduct --worker --master-port=8882 --master-host=127.0.0.1 < ports/$((i+8887))"
done



tmux kill-session -t session3
tmux new-session -d -s session3


tmux new-window -d -t session3 "locust -f locust_online_boutique.py --host=http://10.8.0.4:30440 --master-bind-port=8883 --tags getcart postcart emptycart --master --expect-workers=10 --headless -u $((CART+0)) -r $((CART / RATE)) -t 6m < ports/8885"
for i in $(seq 1 10)
do
    tmux new-window -d -t session3 "locust -f locust_online_boutique.py --host=http://10.8.0.4:30440 --master-port=8883 --tags getcart postcart emptycart --worker --master-host=127.0.0.1 < ports/$((i+8917))"
done
