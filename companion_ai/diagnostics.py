# SPDX-License-Identifier: AGPL-3.0-only
import asyncio
from collections import deque
import time
import psutil


class Metrics:
    def __init__(self):
        self.samples = deque(maxlen=100)
        self.last_error = None
        self.telemetry_latencies = deque(maxlen=1000)
        self.process = psutil.Process()
        self.process.cpu_percent()
        psutil.cpu_percent()

    def record(self, latency, result, first_token=None):
        count, duration = result.get('eval_count', 0), result.get('eval_duration', 0)
        self.samples.append({'response_latency_seconds': round(latency, 3),
            'time_to_first_token_seconds': round(first_token, 3) if first_token is not None else None,
            'tokens_per_second': round(count * 1e9 / duration, 2) if duration else None,
            'output_tokens': count, 'load_seconds': result.get('load_duration', 0) / 1e9,
            'recorded_at': time.time()})
        self.last_error = None

    def record_telemetry(self, elapsed):
        self.telemetry_latencies.append(elapsed * 1000)

    async def snapshot(self):
        gpu = {'available': False}
        process = None
        try:
            process = await asyncio.create_subprocess_exec('nvidia-smi',
                '--query-gpu=name,memory.total,memory.used,utilization.gpu', '--format=csv,noheader,nounits',
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(process.communicate(), 2)
            if process.returncode == 0:
                values = out.decode().strip().splitlines()[0].split(',')
                gpu = dict(available=True, name=values[0].strip(), total_mib=int(values[1]), used_mib=int(values[2]), utilization_percent=int(values[3]))
                gpu['free_mib'] = gpu['total_mib'] - gpu['used_mib']
        except (OSError, TimeoutError, ValueError, IndexError):
            if process and process.returncode is None:
                process.kill()
                await process.wait()
        latencies = sorted(s['response_latency_seconds'] for s in self.samples)
        telemetry = sorted(self.telemetry_latencies)
        return {'telemetry_processing_latency_ms': {'count': len(telemetry), 'p50': telemetry[len(telemetry)//2] if telemetry else None, 'p95': telemetry[min(len(telemetry)-1, int(len(telemetry)*.95))] if telemetry else None, 'max': max(telemetry) if telemetry else None}, 'gpu': gpu, 'system_cpu_percent': psutil.cpu_percent(),
            'backend_cpu_percent': self.process.cpu_percent(),
            'ram_available_gib': round(psutil.virtual_memory().available / 2**30, 2),
            'backend_rss_mib': round(self.process.memory_info().rss / 2**20, 1),
            'last_inference': self.samples[-1] if self.samples else None,
            'inference_count': len(self.samples), 'sample_limit': 100,
            'latency_p50_seconds': latencies[len(latencies)//2] if latencies else None,
            'latency_p95_seconds': latencies[min(len(latencies)-1, int(len(latencies)*.95))] if latencies else None,
            'last_model_error': self.last_error}
