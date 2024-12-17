"""
Execute the locust workload.
Args:
    temp_dir (Path): Temporary directory.
    locustfile (str): Path to the locustfile.
    url (str): URL of the target system.
    workers (int): Number of workers.
"""

import os
import sys
import grpc
import json
import time
import threading
import subprocess
import numpy as np
import google.protobuf.empty_pb2

from concurrent import futures

from protos import collector_pb2
from protos import collector_pb2_grpc


class LatencyCollectorServicer(collector_pb2_grpc.LatencyCollectorServicer):

    def __init__(self, completion_event):
        self.seek_position = 0
        self.completion_event = completion_event
        
        # Store all request latencies in a cache and remove entries that are more than max_query_period old.
        self.request_cache = []
        self.max_query_period = 120

    def read_request_log(self, start_time, period=60):
        latency_data = {}
        num_reads = 0
        num_added = 0

        # First read the relevant data from the cache.
        found_all = False
        first_added = None
        last_added = None
        for entry in self.request_cache:
            if entry["time"] >= start_time:
                request_type = entry["context"]["type"]
                if request_type not in latency_data:
                    latency_data[request_type] = {
                        "latencies": [],
                        "num_fails": 0,
                        "total": 0
                    }

                latency = entry["latency"]
                is_failed = entry["failed"]
                if is_failed == "True":
                    latency_data[request_type]["num_fails"] += 1
                else:
                    latency_data[request_type]["latencies"].append(latency)
                latency_data[request_type]["total"] += 1
                
                num_added += 1
                if first_added is None:
                    first_added = entry["time"]
                last_added = entry["time"]
            
            # Break if the entry is beyond the period.
            if entry["time"] > start_time + period:
                found_all = True
                break
        print(f"Number reads from cache: {num_added}")
        print(f"Time of first added: {first_added}, Time of last added: {last_added}")
        
        # If all data was found in the cache, return the latency data.
        if found_all:
            curr_time = time.time()
            print(f"Provided start time: {start_time}, period: {period}, curr_time: {curr_time}, Added: {num_added}")    
            return latency_data

        with open("request.log", "r") as f:
            f.seek(self.seek_position)
            line = f.readline()
            reached_end = True
            while line:
                data = json.loads(line)
                request_time = data["time"]

                # Add the entry to the cache.
                num_reads += 1
                self.request_cache.append(data)
                last_added = request_time

                # The read position might be stale -- add to latency data if it is within the period.
                if request_time > start_time:
                    request_type = data["context"]["type"]
                    if request_type not in latency_data:
                        latency_data[request_type] = {
                            "latencies": [],
                            "num_fails": 0,
                            "total": 0
                        }

                    latency = data["latency"]
                    is_failed = data["failed"]
                    if is_failed == "True":
                        latency_data[request_type]["num_fails"] += 1
                    else:
                        latency_data[request_type]["latencies"].append(latency)
                    latency_data[request_type]["total"] += 1
                    num_added += 1

                # Break if the request time is beyond the period.
                if request_time > start_time + period:
                    print(f"Breaking at request time: {request_time}")
                    reached_end = False
                    self.seek_position = f.tell()
                    break

                line = f.readline()
            
            # If the end of the file was reached, set the seek position.
            if reached_end:
                self.seek_position = f.tell()

        # Clean the cache of entries that are more than max_query_period old.
        curr_time = time.time()
        self.request_cache = [entry for entry in self.request_cache if curr_time - entry["time"] < self.max_query_period]
        print(f"Provided start time: {start_time}, period: {period}, curr_time: {curr_time}, Added: {num_added}")
        print(f"New reads: {num_reads}, last added: {last_added}, Updated cache size: {len(self.request_cache)}")

        return latency_data

    def CollectAllLatencies(self, request, context):
        # Get the period from the request.
        period = request.period
        start_time = request.start_time
        print(f"Received request for start time: {start_time}, period: {period}")

        # Read request.log, construct the AllLatenciesResponse object and return as response.
        num_latencies = 0
        latency_data = self.read_request_log(start_time, period)
        response = collector_pb2.AllLatenciesResponse()
        for type, latency_data in latency_data.items():
            lat_obj = collector_pb2.LatencyData()
            lat_obj.type = type
            lat_obj.latencies.extend(latency_data["latencies"])

            num_latencies += len(latency_data["latencies"])
            response.data.append(lat_obj)
        print(f"Responding back with {num_latencies} latencies.")

        return response

    def GetLatencyStats(self, request, context):
        # Get the period from the request.
        period = request.period
        start_time = request.start_time
        print(f"Received request for start time: {start_time}, period: {period}")

        # Read request.log, construct the LatencyStatsResponse object and return as response.
        latency_data = self.read_request_log(start_time, period)
        response = collector_pb2.LatencyStatsResponse()
        for type, latency_data in latency_data.items():
            lat_obj = collector_pb2.LatencyStatsData()
            lat_obj.type = type
            if len(latency_data["latencies"]) == 0:
                lat_obj.p95 = 0
                lat_obj.p99 = 0
            else:
                lat_obj.p95 = float(np.percentile(latency_data["latencies"], 95))
                lat_obj.p99 = float(np.percentile(latency_data["latencies"], 99))
            lat_obj.total = latency_data["total"] / period
            lat_obj.failed = latency_data["num_fails"] / period
            print(f"Type: {type}, failed: {lat_obj.failed}, total: {lat_obj.total}")
            response.data.append(lat_obj)

        return response

    def EndCollector(self, request, context):
        self.completion_event.set()
        return google.protobuf.empty_pb2.Empty()


def serve():
    grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))

    # Add a threading event to wait for completion.
    completion_event = threading.Event()
    latency_collector = LatencyCollectorServicer(completion_event)
    collector_pb2_grpc.add_LatencyCollectorServicer_to_server(
        latency_collector, grpc_server
    )
    grpc_server.add_insecure_port("[::]:50051")
    grpc_server.start()

    completion_event.wait()
    grpc_server.stop(0)


def with_locust(temp_dir, locustfile, url, workers):
    args = [
        'locust',
        '--worker',
        '-f', locustfile,
    ]
    worker_ps = []
    for i in range(workers):
        worker_ps.append(subprocess.Popen(args))

    args = [
        'locust',
        '--master',
        '--expect-workers', f'{workers}',
        '--headless',
        '-f', locustfile,
        '-H', url,
        '--csv', f'{temp_dir}/locust',
        '--csv-full-history',
    ]
    master_p = subprocess.Popen(args)

    time.sleep(1)
    return master_p, worker_ps

if __name__ == '__main__':
    # Check the number of arguments.
    if len(sys.argv) != 7:
        print('Usage: python execute_workload.py <temp_dir> <locustfile> <url> <workers> <multiplier> <rps (fixed_* or path to rps file)>')
        sys.exit(1)

    # Multiply the rps by the given factor.
    rps = sys.argv[6]
    multiplier = int(sys.argv[5])
    new_file = os.path.join(os.getcwd(), 'rps.txt')

    # If the rps_file is simply "fixed_*", then use a fixed workload.
    if "fixed" in rps:
        # Get the rate from rps - fixed_<rate>
        rate = int(rps.split('_')[1])
        with open(new_file, 'w') as f:
            for _ in range(3600):
                f.write(f"{rate * multiplier}")
    else:
        rps_file = rps
        with open(rps_file, 'r') as f:
            lines = f.readlines()

        new_lines = [str(int(line) * multiplier) for line in lines]
        with open(new_file, 'w') as f:
            f.write('\n'.join(new_lines))

    # Start the gRPC server.
    serve_thread = threading.Thread(target=serve)
    serve_thread.start()

    # Remove request.log file -- will be used to read the latencies.
    if os.path.exists("request.log"):
        os.remove("request.log")

    # Execute the workload - reads the rps.txt file (new_file variable above).
    p, worker_ps = with_locust(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]))
    p.wait()

    for worker_p in worker_ps:
        worker_p.wait()

    serve_thread.join()
