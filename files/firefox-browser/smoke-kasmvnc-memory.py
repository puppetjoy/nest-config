#!/usr/bin/env python3
"""Bounded TLS HTTP leak regression on a disposable Xvnc, never display :1."""
import http.client
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import time


def memory_kib(pid):
    return {parts[0].rstrip(':'): int(parts[1])
            for line in Path('/proc', str(pid), 'smaps_rollup').read_text().splitlines()
            if (parts := line.split())[0] in ('Pss:', 'Rss:', 'Anonymous:')}


def main():
    # A private synthetic document/certificate; no browser profile or owner data.
    with tempfile.TemporaryDirectory(prefix='kasmvnc-memory-') as directory:
        root = Path(directory)
        (root / 'index.html').write_text('Synthetic KasmVNC memory check\n')
        subprocess.run(['openssl', 'req', '-x509', '-nodes', '-newkey', 'rsa:2048',
                        '-keyout', str(root / 'key.pem'), '-out', str(root / 'cert.pem'),
                        '-days', '1', '-subj', '/CN=localhost'], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # One explicit loopback address avoids KasmVNC's global dual-listener state.
        process = subprocess.Popen([
            os.environ.get('KASMVNC_BINARY', '/opt/kasmweb/bin/Xvnc'), ':94',
            '-interface', '127.0.0.1', '-PublicIP', '127.0.0.1', '-disableBasicAuth',
            '-websocketPort', '6994', '-sslOnly', '1', '-SecurityTypes', 'None',
            '-cert', str(root / 'cert.pem'), '-key', str(root / 'key.pem'),
            '-httpd', str(root), '-geometry', '1365x768', '-RectThreads', '0', '-noreset',
            '-Log', '*:stderr:0'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            # Xvnc allocates a 4 MiB startup buffer after roughly six seconds,
            # even with no HTTP requests. Keep that request-free startup step
            # outside the TLS-retention sample, without relaxing its threshold.
            time.sleep(10)
            if process.poll() is not None:
                raise RuntimeError('disposable Xvnc did not start; test not exercised')
            context = ssl._create_unverified_context()  # Synthetic loopback cert only.
            samples = [{'requests': 0, 'memory_kib': memory_kib(process.pid)}]
            for count in range(1, 301):
                connection = http.client.HTTPSConnection('127.0.0.1', 6994,
                                                         context=context, timeout=5)
                try:
                    connection.request('GET', '/')
                    response = connection.getresponse()
                    body = response.read()
                    assert response.status == 200 and b'Synthetic KasmVNC' in body
                finally:
                    connection.close()
                if count % 50 == 0:
                    time.sleep(.1)
                    samples.append({'requests': count, 'memory_kib': memory_kib(process.pid)})
            # Ignore startup/warm-up. A cache may retain a baseline, not grow per GET.
            growth = samples[-1]['memory_kib']['Pss'] - samples[-3]['memory_kib']['Pss']
            print(json.dumps({'requests_ok': 300, 'samples': samples,
                              'last_100_requests_pss_growth_kib': growth}), flush=True)
            assert growth < 2048, f'TLS HTTP context retention: {growth} KiB per 100 requests'
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    main()
