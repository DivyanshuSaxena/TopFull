# Collect latency and goodput from locust by using REST api

import requests
import time
import csv
import os

import json
import grpc

from protos import collector_pb2
from protos import collector_pb2_grpc

global_config_path = os.environ["GLOBAL_CONFIG_PATH"]
with open(global_config_path, "r") as f:
    global_config = json.load(f)

class Collector:
    def __init__(self, code="online_boutique", type="http"):
        # If type is `grpc`, then start a grpc stub and use it to collect metrics.
        if type == "grpc":
            locust_ip = global_config["locust_url"]
            # For grpc, remove `http://` from the locust url.
            locust_ip = locust_ip.replace("http://", "")
            channel = grpc.insecure_channel(locust_ip + ":50051")
            self.stub = collector_pb2_grpc.LatencyCollectorStub(channel)
            self.last_query_time = time.time()

        if code == "online_boutique":
            self.code = [
                ("GET", "getcart", 8888),
                ("GET", "getproduct", 8888),
                ("POST", "postcart", 8888),
                ("POST", "postcheckout", 8889),
                ("POST", "emptycart", 8888)
            ]
        elif code == "train_ticket":
            self.code = [
                ("POST", "high_speed_ticket", 8089),
                ("POST", "normal_speed_ticket", 8090),
                ("POST", "query_cheapest", 8089),
                ("POST", "query_min_station", 8089),
                ("POST", "query_quickest", 8089),
                ("POST", "query_order", 8089),
                ("POST", "query_order_other", 8090),
                ("GET", "query_route", 8089),
                ("GET", "query_food", 8089),
                ("GET", "enter_station", 8089),
                ("POST", "preserve_normal", 8089),
                ("GET", "query_contact", 8090),
                ("POST", "query_payment", 8090)
            ]
        elif code == "hotel_reservation":
            self.code = [
                ("GET", "user", 8089),
                ("GET", "search", 8089),
                ("GET", "recommend", 8089),
                ("POST", "reserve", 8089)
            ]
        else:
            self.code = code

    def query(self, port=8888):
        """
        Query metrics
        Input: api_code
        Output: metrics of api
        """
        # ports = [8888]
        # ports = [8888, 8889, 8899]
        ports = global_config["locust_port"]
        ports = [i+8888 for i in range(ports)]
        result = {}
        for port in ports:
            try:
                response = requests.get(global_config["locust_url"] + ":" + str(port))
            except:
                continue
            data = response.text
            data = data.split("/")[:-1]
            for i in range(len(self.code)):
                elem = data[i]
                tmp = elem.split("=")

                name = tmp[0]
                rps = tmp[1]
                fail = tmp[2]
                latency95 = tmp[3]
                latency99 = tmp[4]
                if name in result:
                    result[name][0] += float(rps)
                    result[name][1] += float(fail)
                    result[name][2] = max(result[name][2], float(latency95))
                    result[name][3] = max(result[name][3], float(latency99))
                else:
                    result[name] = [float(rps), float(fail), float(latency95), float(latency99)]
        for name in list(result.keys()):
            result[name] = (result[name][0], result[name][1], result[name][2])
            # result[name] = (result[name][0], result[name][1], result[name][2], result[name][3])
        return result

    def query_grpc(self):
        # Get the per-request-type latency stats from locust -- using the gRPC client.
        period = int(time.time() - self.last_query_time)

        print(f"Querying latency stats for period {period} seconds.")
        latency_request = collector_pb2.LatencyRequest()
        latency_request.period = period
        latency_request.start_time = int(self.last_query_time)
        response = self.stub.GetLatencyStats(latency_request)

        result = {}
        for data in response.data:
            result[data.type] = [data.p95, data.p99, data.failed, data.total]
        self.last_query_time = time.time()

        return result


def record_train_ticket():
    collector = Collector(code="train_ticket")
    apis = [i[1] for i in collector.code]
    log_path = "/home/master_artifact/train-ticket/src/logs/"
    proxies = {
        'http': 'http://egg3.kaist.ac.kr:8090'
    }
    url = "http://egg3.kaist.ac.kr:8090/thresholds"

    # Init
    if os.path.exists(log_path+"goodput.csv"):
        os.remove(log_path+"goodput.csv")
    if os.path.exists(log_path+"threshold.csv"):
        os.remove(log_path+"threshold.csv")
    
    with open(log_path+"goodput.csv", "a") as f1:
        with open(log_path+"threshold.csv", "a") as f2:
                w1 = csv.writer(f1)
                w2 = csv.writer(f2)
                w1.writerow(apis)
                w2.writerow(apis)

    # while True:
    for i in range(500):
        time.sleep(2)
        # Record goodput
        goodputs = []
        for i, api in enumerate(apis):
            metric, _ = collector.query(i)
            goodput = metric['current_rps'] - metric['current_fail_per_sec']
            goodputs.append(goodput)

        # Record threshold
        thresholds = []
        response = requests.get(url, proxies=proxies)
        if not response.ok:
            continue
        body = response.text
        body = body.split("/")[:-1]
        for elem in body:
            elem = elem.split("=")
            thresholds.append(float(elem[1]))
        
        # Write csv
        with open(log_path+"goodput.csv", "a") as f1:
            with open(log_path+"threshold.csv", "a") as f2:
                w1 = csv.writer(f1)
                w2 = csv.writer(f2)

                w1.writerow(goodputs)
                w2.writerow(thresholds)

def record_all():
    c = Collector(code=global_config["microservice_code"])
    apis = global_config["record_target"]
    log_path = global_config["record_path"]

    # Init
    for api in apis:
        filename = log_path + api + ".csv"
        if os.path.exists(filename):
            os.remove(filename)

        with open(filename, "a") as f:
            w = csv.writer(f)
            w.writerow(["RPS", "Fail", "Goodput", "Latency95", "Latency99"])
    
    filename = log_path + "total.csv"
    if os.path.exists(filename):
        os.remove(filename)
    with open(filename, "a") as f:
        w = csv.writer(f)
        w.writerow(["RPS", "Fail", "Goodput", "Latency95", "Latency99"])


    while True:
        time.sleep(1)
        metric = c.query()
        total_goodput = {}
        total_rps = 0
        total_fail = 0
        total_latency95 = 0
        total_latency99 = 0

        for i, api in enumerate(apis):
            # rps, fail, latency95, latency99 = metric[api]
            if api not in metric:
                continue
            rps, fail, latency95 = metric[api]
            latency99 = 0
            total_rps += rps
            total_fail += fail
            total_latency95 += latency95
            total_latency99 += latency99
            with open(log_path + api + ".csv", "a") as f:
                w = csv.writer(f)
                w.writerow([rps, fail, rps-fail, latency95, latency99])
                total_goodput[api] = rps-fail
        with open(log_path + "total.csv", "a") as f:
            w = csv.writer(f)
            w.writerow([total_rps, total_fail, total_rps-total_fail, total_latency95/len(apis), total_latency99/len(apis)])
        out = ""
        for api in apis:
            if api in total_goodput:
                out += f"{api}={total_goodput[api]}   "
            else:
                out += f"{api}=0   "
        print(out)

def record_grpc():
    c = Collector(code=global_config["microservice_code"], type="grpc")
    apis = global_config["record_target"]
    log_path = global_config["record_path"]

    # Make the log directory if it doesn't exist.
    if not os.path.exists(log_path):
        os.makedirs(log_path)

    # Init
    api_filenames = {}
    for api in apis:
        filename = os.path.join(log_path, api + ".csv")
        if os.path.exists(filename):
            os.remove(filename)

        api_filenames[api] = filename
        with open(filename, "a") as f:
            w = csv.writer(f)
            w.writerow(["RPS", "Fail", "Goodput", "Latency95", "Latency99"])
    print(f"{api_filenames} created.")
    
    total_filename = os.path.join(log_path, "total.csv")
    if os.path.exists(total_filename):
        os.remove(total_filename)
    with open(total_filename, "a") as f:
        w = csv.writer(f)
        w.writerow(["RPS", "Fail", "Goodput", "Latency95", "Latency99"])

    # Query every one minute.
    period = 60
    while True:
        print(f"Sleeping for {period} seconds.")
        time.sleep(period)
        metric = c.query_grpc()
        print(f"Received metrics")
        total_goodput = {}
        total_rps = 0
        total_fail = 0
        total_latency95 = 0
        total_latency99 = 0

        for i, api in enumerate(apis):
            # rps, fail, latency95, latency99 = metric[api]
            if api not in metric:
                latency95, latency99, fail, rps = 0, 0, 0, 0
            else:
                latency95, latency99, fail, rps = metric[api]

            total_rps += rps / period
            total_fail += fail / period
            total_latency95 += latency95
            total_latency99 += latency99
            with open(api_filenames[api], "a") as f:
                w = csv.writer(f)
                w.writerow([rps, fail, rps-fail, latency95, latency99])
                total_goodput[api] = rps - fail
        with open(total_filename, "a") as f:
            w = csv.writer(f)
            w.writerow([total_rps, total_fail, total_rps-total_fail, total_latency95/len(apis), total_latency99/len(apis)])
        
        print("Written to api and total files.")
        
        out = ""
        for api in apis:
            if api in total_goodput:
                out += f"{api}={total_goodput[api]}   "
            else:
                out += f"{api}=0   "
        print(out)

import csv
if __name__ == "__main__":
    record_grpc()
