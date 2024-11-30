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
import google.protobuf.empty_pb2

from concurrent import futures

from protos import collector_pb2
from protos import collector_pb2_grpc


class LatencyCollectorServicer(collector_pb2_grpc.LatencyCollectorServicer):

    def __init__(self, completion_event):
        self.last_query_time = None
        self.seek_position = 0
        self.completion_event = completion_event

    def CollectLatency(self, request, context):
        # Get the period from the request.
        period = request.period
        print(f"Received request for period: {request.period}")

        # Read request.log, construct the LatencyResponse object and return as response.
        latency_data = {}
        with open("request.log", "r") as f:
            f.seek(self.seek_position)
            line = f.readline()
            while line:
                data = json.loads(line)
                request_type = data["context"]["type"]
                latency = data["latency"]

                if request_type not in latency_data:
                    latency_data[request_type] = []
                latency_data[request_type].append(latency)

                if self.last_query_time is None:
                    self.last_query_time = data["time"]

                if data["time"] - self.last_query_time > period:
                    self.seek_position = f.tell()
                    self.last_query_time = data["time"]
                    break

                line = f.readline()

        num_latencies = 0
        response = collector_pb2.LatencyResponse()
        for type, latencies in latency_data.items():
            lat_obj = collector_pb2.LatencyData()
            lat_obj.type = type
            lat_obj.latencies.extend(latencies)

            num_latencies += len(latencies)
            response.data.append(lat_obj)
        print(f"Responding back with {num_latencies} latencies.")

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
        print('Usage: python execute_workload.py <temp_dir> <locustfile> <url> <workers> <multiplier> <rps_file>')
        sys.exit(1)

    # Multiply the rps by the given factor.
    rps_file = sys.argv[6]
    multiplier = int(sys.argv[5])
    new_file = os.path.join(os.getcwd(), 'rps.txt')

    with open(rps_file, 'r') as f:
        lines = f.readlines()

    new_lines = [str(int(line) * multiplier) for line in lines]
    with open(new_file, 'w') as f:
        f.write('\n'.join(new_lines))

    # Start the gRPC server.
    serve_thread = threading.Thread(target=serve)
    serve_thread.start()

    p, worker_ps = with_locust(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]))
    p.wait()

    for worker_p in worker_ps:
        worker_p.wait()

    serve_thread.join()
