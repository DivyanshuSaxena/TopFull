import gym, ray
from ray.rllib.algorithms import ppo
import random
import numpy as np
from skeleton_simulator import *
from metric_collector import Collector
from overload_detection import *
import csv
import threading
import sys
import json

global_config_path = os.environ["GLOBAL_CONFIG_PATH"]
with open(global_config_path, "r") as f:
    global_config = json.load(f)

N_DISCRETE_ACTIONS = 5
feature = 2
MAX_STEPS = 50
addstep = 5
mulstep = 0.1

# Certificates hyperparameters
delta = 0.1
alpha = 1
use_certificates = False

class MyEnv(gym.Env):
    def __init__(self, env_config):
        self.action_space = gym.spaces.Box(low=np.array([-0.5]), high=np.array([0.5]), dtype=np.float32)
        self.observation_space = gym.spaces.Box(low=np.array([-2000.0, -1000.0]), high=np.array([2000.0, 50000.0]), dtype=np.float32)
        self.MAX_STEPS = MAX_STEPS
        self.addstep = addstep
        self.mulstep = mulstep

    def reset(self):
        self.ts = Simulator(addstep,mulstep)
        self.goodput = self.ts.currGoodput
        self.maxgoodput = self.ts.targetGoodput
        self.count = 0
        self.stopcount = 0
        initdelta = self.ts.simGoodput(0) - self.goodput
        self.state = np.array([initdelta, self.ts.simLatency(0)])
        self.reward = 0
        self.done = False
        self.info = {}
        return self.state

    def step(self, action):
        if self.done:
            print("EPISODE DONE!!!") 
        elif self.count == self.MAX_STEPS:
            self.reward = -40 
            self.done = True
        elif self.stopcount == 3:
            if self.maxgoodput > self.goodput + addstep*3:
                self.reward = -(100-self.count) 
            else:
                self.reward = (100-self.count) 
            self.done = True
        else:
            self.count += 1
            tmpGoodput = self.goodput
            self.goodput = self.ts.simGoodput(action)
            self.maxgoodput = max(self.goodput, self.maxgoodput)
            deltaGoodput = self.goodput - tmpGoodput
            self.state = np.array([deltaGoodput, self.ts.simLatency(action)])
            self.reward = deltaGoodput
            if action == 0:
                self.stopcount += 1
            else:
                self.stopcount = 0
                self.reward -= 0.01*self.count

        return self.state, self.reward, self.done, self.info

def run_agent(agent, event):
    while True:
        if agent.terminate:
            sys.exit()
        time.sleep(agent.interval)
        if not event.is_set():
            agent.run()

class Agent:
    def __init__(self, target_apis, algo, interval=2, alpha=0.9, ttl=15000, code='online_boutique'):
        self.target_apis = target_apis
        self.collector = Collector(code=code, type="grpc")
        self.interval = interval
        self.alpha = alpha
        self.terminate = False
        self.detector = Detector()
        self.detector.reset(self.target_apis)
        self.ttl = ttl
        self.algo = algo
        self.disaggregate = False
        self.disaggregate_apis = []

        self.threshold = 0
        for api in self.target_apis:
            self.threshold += self.detector.apis[api]['threshold']
        print(f"Start agent with target API {self.target_apis}")

        self.target_services = []
        for api in self.target_apis:
            self.target_services += self.detector.apis[api]['execution_path']
        self.target_services = list(set(self.target_services))
    

    def run(self):
        print(f"{self.target_apis} running")
        # return
        if self.ttl <= 0:
            self.stop(reset=True)
            print("ttl done")
            return
        # Get Goodput
        goodput = 0
        clean_apis = []
        rps = self.detector.current_rps()

        metric = self.collector.query_grpc()
        latencys = []
        for api in self.target_apis:
            # api_rps, api_fail, api_latency, _ = metric[api]
            # api_rps, api_fail, api_latency = metric[api]
            if api not in metric:
                continue

            api_latency99 = metric[api][1]
            api_fail = metric[api][2]
            api_rps = metric[api][3]
            latencys.append(api_latency99)
            goodput += api_rps - api_fail

            if api_fail <= 0.1 * api_rps and self.detector.apis[api]['threshold'] >= rps.get(api) or rps.get(api) == 0:
                clean_apis.append(api)
                # print(f"{api} is clean. RPS: {api_rps}, Fail: {api_fail}, Threshold: {self.detector.apis[api]['threshold']}")
        if self.threshold == 0:
            self.stop(reset=True)
            print("zero threshold")
            return
        
        # Disaggregate decision
        tmp_overload_services = self.detector.detect(0.8)
        disaggregate_apis = []
        for api in self.target_apis:
            flag = True
            for svc in self.detector.apis[api]['execution_path']:
                if svc in tmp_overload_services:
                    flag = False
                    break
            if flag:
                disaggregate_apis.append(api)

        if len(disaggregate_apis) > 0 and len(self.target_apis) > 1:
            self.disaggregate = True
            self.disaggregate_apis = disaggregate_apis
            self.stop(reset=False)
            return
            

        state = goodput / self.threshold
        latency = max(latencys)

        # Check termination state
        if len(clean_apis) == len(self.target_apis):
            self.stop(reset=True)
            print("All APIs clean")
            return

        # RL
        obs = np.array([state, latency]) 
        action = self.algo.compute_single_action(obs)

        # print("----------")
        # print(f"Threshold: {self.threshold} -> Goodput: {goodput}")
        # print(f"From observation {obs}, action: {action}")
        self.detector.apply_v2(float(action), self.target_apis, [])
        
        self.threshold = 0
        for api in self.target_apis:
            self.threshold += self.detector.apis[api]['threshold']
        
        self.ttl -= 1

    def add_apis(self, new_apis):
        rps = self.detector.current_rps()
        for api in new_apis:
            self.detector.apis[api]['threshold'] = rps.get(api, 0)
        self.detector.reset(new_apis)
        self.target_apis += new_apis

        self.target_services = []
        for api in self.target_apis:
            self.target_services += self.detector.apis[api]['execution_path']
        self.target_services = list(set(self.target_services))

        self.threshold = 0
        for api in self.target_apis:
            self.threshold += self.detector.apis[api]['threshold']
    
    def add_apis_with_threshold(self, new_apis):
        apis = []
        for api, threshold in new_apis:
            self.detector.apis[api]['threshold'] = threshold
            self.target_apis.append(api)
            apis.append(api)

        self.target_services = []
        for api in self.target_apis:
            self.target_services += self.detector.apis[api]['execution_path']
        self.target_services = list(set(self.target_services))

        self.detector.reset(apis)
        self.threshold = 0
        for api in self.target_apis:
            self.threshold += self.detector.apis[api]['threshold']
    
    def stop(self, reset=False):
        # print(f"Stop agent with target API {self.target_apis}")
        if reset:
            for api in self.target_apis:
                self.detector.apis[api]['threshold'] = 10000
            self.detector.reset(self.target_apis)
        self.terminate = True
        # self.detector.event.set()


# Check if a checkpoint path is provided as command line argument.
# If so, use that checkpoint else the one in global config.
if len(sys.argv) > 1:
    checkpoint_path = sys.argv[1]
    print(f"Using checkpoint path: {checkpoint_path}")
else:
    checkpoint_path = global_config["checkpoint_path"]

# Initialize RL
ray.init()
algo = ppo.PPO(env=MyEnv, config={
    "env_config": {
        'api': 1
    },
    'num_workers': 1  # config to pass to env class
})
ts = Simulator(addstep,mulstep)
if os.path.exists(checkpoint_path):
    algo.restore(checkpoint_path)

detector = Detector()
current_agent = []
log_path = global_config["record_path"]
if os.path.exists(log_path + "num_agent.csv"):
    os.remove(log_path+"num_agent.csv")
if os.path.exists(log_path + "execution_time.csv"):
    os.remove(log_path+"execution_time.csv")

# Start Loop
while True:
    time.sleep(2)
    # Clean stopped agents
    tmp_current_agent = []
    for i in range(len(current_agent)):
        if current_agent[i][0].terminate:
            if current_agent[i][0].disaggregate:
                print("Disaggregate!")
                disaggregate_apis = current_agent[i][0].disaggregate_apis
                remain_apis = list(set(current_agent[i][0].target_apis) - set(disaggregate_apis))


                for api in disaggregate_apis:
                    new_agent = Agent([], algo, interval=5, code=global_config["microservice_code"])
                    new_event = threading.Event()
                    new_event.set()
                    tid = threading.Thread(target=run_agent, args=(new_agent, new_event))
                    tid.start()
                    tmp_current_agent.append((new_agent, tid, new_event))

                    new_agent.add_apis_with_threshold([(api, current_agent[i][0].detector.apis[api]['threshold'])])
                    new_event.clear()
                
                new_agent = Agent([], algo, interval=5, code=global_config["microservice_code"])
                new_event = threading.Event()
                new_event.set()
                tid = threading.Thread(target=run_agent, args=(new_agent, new_event))
                tid.start()
                tmp_current_agent.append((new_agent, tid, new_event))

                tmp = []
                for api in remain_apis:
                    tmp.append((api, current_agent[i][0].detector.apis[api]['threshold']))
                new_agent.add_apis_with_threshold(tmp)
                new_event.clear()

            current_agent[i] = None
    current_agent += tmp_current_agent
    current_agent = [i for i in current_agent if i is not None]
    with open(log_path + "num_agent.csv", "a") as f:
        w = csv.writer(f)
        w.writerow([len(current_agent)])

    # Detect overload
    overloaded_services = detector.detect(0.8)
    if len(overloaded_services) == 0:
        print("No overloaded services")
        continue
    for svc in overloaded_services:
        cluster_apis = detector.clustering([svc])
        print(cluster_apis)
        if len(cluster_apis) == 0:
            continue
        valid_agent = []
        flag = 3
        if len(current_agent) > 0:
            i = 0
            for agent, agent_tid, event in current_agent:
                if len(set(cluster_apis) - set(agent.target_apis)) == 0:
                    valid_agent.append((agent, agent_tid, event, i))
                    flag = 1
                    break
                elif len(set(cluster_apis) - set(agent.target_apis)) < len(set(cluster_apis)):
                    valid_agent.append((agent, agent_tid, event, i))
                    flag = 2
                i += 1
        
        # Major premise: Target apis in agents are independent each other
        # Case 1: All apis in cluster already exist in an agent
        # Action: Do nothing
        print("number of valid agent")
        print(len(valid_agent))
        if flag == 1 and len(valid_agent) == 1:
            # end_time = time.perf_counter()
            # print("execution time:",end_time-start_time)
            # with open(log_path+ "execution_time.csv", "a") as f2:
            #     w2 = csv.writer(f2)
            #     w2.writerow([end_time-start_time])
            continue

        # Case 2: Some apis in cluster exist in an agent, but some do not
        # Action: Add new apis to the agent
        elif flag == 2 and len(valid_agent) == 1:
            agent = valid_agent[0][0]
            event = valid_agent[0][2]
            apis_to_append = list(set(cluster_apis) - set(agent.target_apis))
            event.set()
            agent.add_apis(apis_to_append)
            event.clear()
            

        # Case 3: All apis in the cluster don't exist in any agent
        # Action: Create a new agent with the cluster
        elif len(valid_agent) == 0:
            new_agent = Agent(cluster_apis, algo, code=global_config["microservice_code"], interval=5) 
            new_event = threading.Event()
            tid = threading.Thread(target=run_agent, args=(new_agent, new_event))
            tid.start()
            current_agent.append((new_agent, tid, new_event))
        
        # Case 4: Apis in the cluster exist in multiple agents
        # Action: Merge all the agents
        else:
            main_agent, _, main_event, _ = valid_agent[0]
            main_event.set()
            apis_to_append = set(cluster_apis) - set(main_agent.target_apis)
            for tmp_agent, tmp_tid, tmp_event, i in valid_agent[1:]:
                tmp = []
                for api in tmp_agent.target_apis:
                    tmp.append((api, tmp_agent.detector.apis[api]['threshold']))
                main_agent.add_apis_with_threshold(tmp)
                current_agent[i] = None
                tmp_agent.stop(False)
                apis_to_append -= set(tmp_agent.target_apis)
            
            main_agent.add_apis(list(apis_to_append))
            main_event.clear()
            current_agent = [i for i in current_agent if i is not None]
