"""Isolated production-access nginx fixture; upstream and proxy share a netns."""
import base64
import json
from pathlib import Path
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixture_resources import FixtureResources
from test_private_access import CLIENT, IMAGE, PYTHON, ROOT, run

UPSTREAM = '''
import hashlib, http.server, json
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({'path':self.path,'headers':dict(self.headers),
          'body_bytes':len(body),'body_sha256':hashlib.sha256(body).hexdigest()}).encode())
    do_POST = do_GET
    def log_message(self, *args): pass
http.server.ThreadingHTTPServer(('0.0.0.0',8000),Handler).serve_forever()
'''


class ProductionAccessFixture(unittest.TestCase):
    allow_loopback = True

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix='joyride-production-access-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.resources = FixtureResources(cls)
        cls.path = Path(cls.directory.name)
        cls.path.chmod(0o755)
        cls.container = 'joyride-production-access-' + uuid.uuid4().hex[:12]
        cls.upstream = cls.container + '-upstream'
        cls.network = cls.container + '-network'
        config_path = ROOT / 'files/app/joyride/production-access-nginx.conf'
        if not config_path.is_file():
            raise RuntimeError(f'Parent fixture config is not present: {config_path}')
        config = config_path.read_text()
        if cls.allow_loopback:
            config = config.replace('allow 172.22.4.3/32;', 'allow 127.0.0.1/32;')
        for hostname, port in (('joyride-internal-web.joyride.svc.cluster.local', 8003),
                               ('joyride-trusted-production.joyride.svc.cluster.local', 8004)):
            config = config.replace(f'{hostname}:{port}', '127.0.0.1:8000')
        (cls.path / 'nginx.conf').write_text(config)
        run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
            '-subj', '/CN=joyride.eyrie', '-addext', 'subjectAltName=DNS:joyride.eyrie',
            '-keyout', str(cls.path / 'tls.key'), '-out', str(cls.path / 'tls.crt'))
        (cls.path / 'tls.key').chmod(0o644)
        architecture = run('podman', 'info', '--format', '{{.Host.Arch}}').stdout.strip()
        for image in (PYTHON, IMAGE):
            # Use cached pinned images; only pull when absent locally.
            present = subprocess.run(['podman', 'image', 'exists', image]).returncode == 0
            if not present:
                run('podman', 'pull', '--platform', 'linux/' + architecture, image)
        run('podman', 'network', 'create', *cls.resources.labels, '--internal', cls.network)
        run('podman', 'create', *cls.resources.labels, '--name', cls.upstream,
            '--network', cls.network, '--cap-drop=ALL', '--security-opt', 'no-new-privileges',
            PYTHON, 'python', '-u', '-c', UPSTREAM)
        run('podman', 'cp', str(cls.path), cls.upstream + ':/tls')
        run('podman', 'start', cls.upstream)
        run('podman', 'create', *cls.resources.labels, '--name', cls.container,
            '--network', 'container:' + cls.upstream, '--read-only', '--cap-drop=ALL',
            '--security-opt', 'no-new-privileges', '--user', '10001:10001',
            '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m,mode=1777', '--entrypoint', 'nginx',
            IMAGE, '-g', 'daemon off;')
        run('podman', 'cp', str(cls.path), cls.container + ':/tls')
        run('podman', 'cp', str(cls.path / 'nginx.conf'), cls.container + ':/etc/nginx/nginx.conf')
        run('podman', 'start', cls.container)
        run('podman', 'exec', cls.container, 'nginx', '-t')
        for _ in range(40):
            try:
                status, _ = cls.request('/ops/status')
                expected = 200 if cls.allow_loopback else 403
                if status == expected:
                    break
            except RuntimeError:
                pass
            time.sleep(0.25)
        else:
            raise RuntimeError(run('podman', 'logs', cls.container).stderr)

    @classmethod
    def request(cls, path='/ops/status', host='joyride.eyrie', sni='joyride.eyrie', extra='', method='GET', size=0, framing='length'):
        result = json.loads(run('podman', 'exec', cls.upstream, 'python', '-c', CLIENT,
            '127.0.0.1', path, host, sni, extra, method, str(size), framing).stdout)
        if result.get('ssl_error'):
            raise ssl.SSLError('Fixture TLS handshake rejected')
        return result['status'], base64.b64decode(result['data'])


class ProductionAccessAllowed(ProductionAccessFixture):
    allow_loopback = True

    def test_exact_production_routes_and_method_refusals(self):
        allowed = [('/ops/status','GET'),('/ops/diagnostics','GET'),('/ops/roster','GET'),
                   ('/ops/releases','GET'),('/ops/releases/frontend','POST'),
                   ('/ops/releases/content','POST'),('/routing/status','GET'),
                   ('/routing/import','POST'),('/routing/reviews','GET')]
        for path, method in allowed:
            with self.subTest(path=path, method=method):
                self.assertEqual(self.request(path=path, method=method)[0], 200)
        forbidden = ['/ops/arbitrary','/ops/deploy','/delivery/queue',
                     '/ops/members/x/membership/set','/ops/members/x/member/reconcile']
        for path in forbidden:
            self.assertIn(self.request(path=path, method='POST')[0], (404, 405))
        for path in ('/ops/status','/ops/diagnostics','/ops/roster','/ops/releases','/routing/status'):
            self.assertEqual(self.request(path=path, method='POST')[0], 405)
        self.assertEqual(self.request(path='/routing/import', method='GET')[0], 405)
        self.assertEqual(self.request(path='/ops/releases/frontend', method='GET')[0], 405)
        self.assertEqual(self.request(path='/ops/releases/content', method='GET')[0], 405)

    def test_exact_targets_queries_and_raw_aliases_are_refused(self):
        for path in ('/ops/status?x=1','/ops/status?','/ops/%73tatus','//ops/status',
                     '/ops//status','/other/../ops/status','/routing/status?x=1',
                     '/routing/%73tatus','/routing//status','/routing/import?','/routing/%69mport',
                     '/routing/reviews?cursor=1','/routing/reviews?before=1',
                     '/ops/members/x/membership/set','/ops/members/x/membership-set'):
            with self.subTest(path=path):
                self.assertIn(self.request(path=path)[0], (400,404))

    def test_allowlisted_trusted_headers_are_preserved_and_spoofed_headers_stripped(self):
        cases = [('/ops/releases/frontend','POST', 'Content-Type: application/json\r\nX-Release-Sha256: fixture-sha\r\nX-Release-Version: fixture-version\r\nX-Previous-Sha256: fixture-prev\r\nX-Source-Head: fixture-head\r\nX-Joyride-Trusted-Test: forged\r\nForwarded: forged\r\nCookie: forged\r\nAuthorization: forged\r\n'),
                 ('/routing/reviews','GET','Content-Type: application/json\r\nX-CAS-Token: fixture-cas\r\nIdempotency-Key: fixture-idem\r\nX-Joyride-Trusted-Test: forged\r\nForwarded: forged\r\nCookie: forged\r\nAuthorization: forged\r\n')]
        for path, method, extra in cases:
            status, data = self.request(path=path, method=method, extra=extra)
            self.assertEqual(status, 200)
            headers = json.loads(data)['headers']
            for spoof in ('forged',):
                self.assertNotIn(spoof, data.decode())
            self.assertNotIn('Authorization', headers)
            self.assertNotIn('Cookie', headers)
            self.assertNotIn('Forwarded', headers)

    def test_body_caps_are_admitted_at_limit_and_reject_declared_oversize(self):
        for path, limit in (('/routing/import',1024*1024),('/routing/reviews',8*1024*1024),
                            ('/ops/releases/frontend',32*1024*1024),
                            ('/ops/releases/content',192*1024*1024)):
            with self.subTest(path=path):
                # Header-only probes avoid sending oversized payloads.
                method = 'GET' if path == '/routing/reviews' else 'POST'
                status, _ = self.request(path=path, method=method,
                    extra=f'Content-Length: {limit + 1}\r\n')
                self.assertEqual(status, 413)

    def test_host_and_sni_are_exact(self):
        self.assertEqual(self.request(host='joyride.eyrie:443')[0], 200)
        for host in ('joyride-ops.eyrie','joyride.eyrie.attacker.invalid','joyride.eyrie:8001'):
            self.assertEqual(self.request(host=host)[0], 421)
        with self.assertRaises(ssl.SSLError):
            self.request(sni='wrong.eyrie')

    def test_owner_fallback_keeps_session_csrf_headers(self):
        extra = ('Cookie: sessionid=fixture; csrftoken=fixture\r\nX-CSRFToken: fixture\r\n'
                 'Origin: https://joyride.eyrie\r\nX-Joyride-Trusted-Test: forged\r\n'
                 'Tailscale-User-Login: forged\r\n')
        status, data = self.request(path='/admin/routing/reviews', method='POST', extra=extra)
        self.assertEqual(status, 200)
        headers = json.loads(data)['headers']
        self.assertEqual(headers.get('Cookie'), 'sessionid=fixture; csrftoken=fixture')
        self.assertEqual(headers.get('X-CSRFToken'), 'fixture')
        self.assertEqual(headers.get('Origin'), 'https://joyride.eyrie')
        self.assertNotIn('forged', data.decode())


class ProductionAccessDenied(ProductionAccessFixture):
    allow_loopback = False

    def test_exact_source_cidr_denies_loopback_even_with_forwarding_spoof(self):
        for path in ('/ops/status','/ops/diagnostics','/routing/status'):
            status, _ = self.request(path=path, extra=(
                'X-Forwarded-For: 172.22.4.3\r\nForwarded: for=172.22.4.3\r\n'
                'Tailscale-User-Login: joy\r\n'))
            self.assertEqual(status, 403)


if __name__ == '__main__':
    unittest.main(verbosity=2)
