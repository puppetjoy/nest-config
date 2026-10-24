"""Exercise the real pinned nginx listener without cluster credentials.

Run with python3 spec/app/joyride/test_private_access.py. Requires Podman/OpenSSL.
Upstreams are explicit local fixtures, not substitutes for live app acceptance.
"""
import base64
import json
from pathlib import Path

import ssl
import subprocess
import tempfile

import time
import unittest
import uuid
import xml.etree.ElementTree as ET

from fixture_resources import FixtureResources

ROOT = Path(__file__).resolve().parents[3]
IMAGE = "mirror.gcr.io/nginxinc/nginx-unprivileged@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03"
PYTHON = "mirror.gcr.io/library/python@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641"
UPSTREAM = '''
import http.server, json
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps({'path':self.path,'headers':dict(self.headers)}).encode())
    def log_message(self, format, *args):
        pass
    do_POST = do_GET
http.server.ThreadingHTTPServer(('0.0.0.0', 8000), Handler).serve_forever()
'''
CLIENT = '''
import base64, http.client, json, socket, ssl, sys
target, path, host, sni, extra, method = sys.argv[1:]
try:
    context = ssl.create_default_context(cafile='/tls/tls.crt')
    with socket.create_connection((target,8443),timeout=5) as raw:
        with context.wrap_socket(raw,server_hostname=sni) as sock:
            sock.sendall((method+' '+path+' HTTP/1.1\\r\\nHost: '+host+'\\r\\nConnection: close\\r\\n'+extra+'\\r\\n').encode())
            response = http.client.HTTPResponse(sock, method=method)
            response.begin()
            data = response.read()
            status = response.status
    print(json.dumps({'status':status, 'data':base64.b64encode(data).decode()}))
except ssl.SSLError:
    print(json.dumps({'ssl_error':True}))
'''


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result


class PrivateAccess(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="joyride-private-access-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.resources = FixtureResources(cls)
        cls.path = Path(cls.directory.name)
        cls.path.chmod(0o755)
        cls.container = "joyride-access-test-" + uuid.uuid4().hex[:12]
        cls.upstream = cls.container + "-upstream"
        cls.network = cls.container + "-network"
        config = (ROOT / "files/app/joyride/test-access-nginx.conf").read_text()
        for name, port in (("internal-web", 8003), ("trusted-test", 8002), ("ops", 8001)):
            config = config.replace(f"joyride-test-{name}.test.svc.cluster.local:{port}", f"{cls.upstream}:8000")
        (cls.path / "nginx.conf").write_text(config)
        run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=joyride-test.eyrie", "-addext", "subjectAltName=DNS:joyride-test.eyrie", "-keyout", str(cls.path / "tls.key"), "-out", str(cls.path / "tls.crt"))
        (cls.path / "tls.key").chmod(0o644)  # Disposable fixture, never a managed key.
        try:
            # No host networking, published ports or bind mounts: works with remote CI Podman.
            architecture = run("podman", "info", "--format", "{{.Host.Arch}}").stdout.strip()
            for image in (PYTHON, IMAGE):
                run("podman", "pull", "--platform", "linux/" + architecture, image)
            run("podman", "network", "create", *cls.resources.labels, "--internal", cls.network)
            run("podman", "create", *cls.resources.labels, "--name", cls.upstream, "--network", cls.network, "--cap-drop=ALL", "--security-opt", "no-new-privileges", PYTHON, "python", "-u", "-c", UPSTREAM)
            run("podman", "cp", str(cls.path), cls.upstream + ":/tls")
            run("podman", "start", cls.upstream)
            upstream_info = json.loads(run("podman", "inspect", cls.upstream).stdout)[0]
            upstream_ip = upstream_info["NetworkSettings"]["Networks"][cls.network]["IPAddress"]
            (cls.path / "nginx.conf").write_text(config.replace(cls.upstream + ":8000", upstream_ip + ":8000"))
            run("podman", "create", *cls.resources.labels, "--name", cls.container, "--network", cls.network, "--read-only", "--cap-drop=ALL", "--security-opt", "no-new-privileges", "--user", "101:101", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m,mode=1777", "--entrypoint", "nginx", IMAGE, "-g", "daemon off;")
            run("podman", "cp", str(cls.path), cls.container + ":/tls")
            run("podman", "cp", str(cls.path / "nginx.conf"), cls.container + ":/etc/nginx/nginx.conf")
            run("podman", "start", cls.container)
            nginx_info = json.loads(run("podman", "inspect", cls.container).stdout)[0]
            cls.address = nginx_info["NetworkSettings"]["Networks"][cls.network]["IPAddress"]
            for _ in range(30):
                try:
                    probe = run("podman", "exec", cls.upstream, "python", "-c", CLIENT, cls.address, "/", "joyride-test.eyrie", "joyride-test.eyrie", "", "GET")
                    if json.loads(probe.stdout).get("status") == 200:
                        break
                except RuntimeError:
                    pass
                time.sleep(0.2)
            else:
                logs = run("podman", "logs", cls.container)
                raise RuntimeError(logs.stdout + logs.stderr)
        except Exception:
            # unittest runs registered class cleanups even when setup fails.
            raise

    def request(self, path="/", host="joyride-test.eyrie", sni="joyride-test.eyrie", extra="", method="GET"):
        result = json.loads(run("podman", "exec", self.upstream, "python", "-c", CLIENT, self.address, path, host, sni, extra, method).stdout)
        if result.get("ssl_error"):
            raise ssl.SSLError("Fixture TLS handshake rejected")
        return result["status"], base64.b64decode(result["data"])

    def test_home(self):
        self.assertEqual(self.request()[0], 200)

    def test_exact_origin_with_standard_port(self):
        self.assertEqual(self.request(host="joyride-test.eyrie:443")[0], 200)

    def test_shared_ingress_host_is_not_forwarded(self):
        self.assertEqual(self.request(host="gitlab-test.eyrie")[0], 421)

    def test_host_suffix_is_not_accepted(self):
        self.assertEqual(self.request(host="joyride-test.eyrie.attacker.invalid")[0], 421)

    def test_wrong_port_is_not_accepted(self):
        self.assertEqual(self.request(host="joyride-test.eyrie:8001")[0], 421)

    def test_wrong_sni_fails_handshake(self):
        with self.assertRaises(ssl.SSLError):
            self.request(sni="gitlab-test.eyrie")

    def test_private_controller_is_absent(self):
        self.assertEqual(self.request(path="/delivery/queue")[0], 404)

    def test_roster_and_arbitrary_ops_are_absent(self):
        for path in ("/ops/roster", "/ops/arbitrary"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path=path)[0], 404)

    def test_admin_reaches_internal_application_authorization(self):
        self.assertEqual(self.request(path="/admin")[0], 200)

    def test_release_routes_are_exact_and_preserve_only_release_headers(self):
        self.assertEqual(self.request(path="/ops/releases")[0], 200)
        self.assertEqual(self.request(path="/ops/releases", method="POST")[0], 405)
        for kind in ("frontend", "content"):
            path = "/ops/releases/" + kind
            self.assertEqual(self.request(path=path)[0], 405)
            status, data = self.request(path=path, method="POST", extra=(
                "Content-Type: application/octet-stream\r\nX-Release-Sha256: fixture-sha\r\n"
                "X-Previous-Sha256: fixture-previous\r\nX-Release-Version: fixture-version\r\n"
                "X-Source-Head: fixture-head\r\nAuthorization: fixture-secret\r\n"
                "X-Joyride-Trusted-Test: forged\r\n"))
            self.assertEqual(status, 200)
            for value in (b"fixture-sha", b"fixture-previous", b"fixture-version", b"fixture-head"):
                self.assertIn(value, data)
            self.assertNotIn(b"fixture-secret", data)
            self.assertNotIn(b"forged", data)
            for suffix in ("?x=1", "/", "/extra"):
                self.assertEqual(self.request(path=path + suffix, method="POST")[0], 404)
            limit = 64 * 1024 * 1024 if kind == "content" else 32 * 1024 * 1024
            self.assertEqual(self.request(path=path, method="POST", extra=f"Content-Length: {limit + 1}\r\n")[0], 413)

    def test_member_routes_are_token_free_and_preserve_only_content_and_idempotency(self):
        pairs = [("GET", ""), ("GET", "/audit")]
        pairs += [("POST", "/" + op) for op in (
            "waiver/reset", "waiver/record", "subscription/cancel", "membership/set", "sessions/revoke")]
        for method, suffix in pairs:
            path = "/ops/members/synthetic%2Bfixture%40example.invalid" + suffix
            self.assertEqual(self.request(path=path, method=method)[0], 200)
            status, data = self.request(path=path, method=method, extra=(
                "Authorization: Bearer synthetic-fixture\r\nIdempotency-Key: fixture-member-1\r\n"
                "Content-Type: application/json\r\nX-Joyride-Trusted-Test: forged\r\n"
                "Tailscale-User-Login: forged\r\nForwarded: forged\r\n"
                "X-Joyride-Identity: forged\r\nTrusted-Test-Listener: forged\r\nCookie: forged\r\n"))
            self.assertEqual(status, 200)
            headers = json.loads(data)["headers"]
            self.assertNotIn("Authorization", headers)
            self.assertEqual(json.loads(data)["path"], path)
            self.assertEqual(headers["Idempotency-Key"], "fixture-member-1")
            self.assertEqual(headers["Content-Type"], "application/json")
            self.assertNotIn(b"forged", data)
            wrong = "POST" if method == "GET" else "GET"
            self.assertEqual(self.request(path=path, method=wrong)[0], 405)
        self.assertEqual(self.request(path="/ops/members/x/waiver/reset", method="POST", extra="Content-Length: 8193\r\n")[0], 413)

    def test_member_audit_cursor_contract(self):
        base = "/ops/members/synthetic%40example.invalid/audit"
        cursor = "bfa1494e-0443-4c8a-9aab-1074b615f2a3"
        for query in ("", "?before=" + cursor, "?history_before=42",
                      "?before=" + cursor + "&history_before=42",
                      "?history_before=42&before=" + cursor):
            status, data = self.request(path=base + query)
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(data)["path"], base + query)
        for query in ("?", "?before=1&before=2", "?history_before=1&history_before=2",
                      "?unknown=1", "?before=1&unknown=2", "?%62efore=1", "?before=%2531"):
            self.assertEqual(self.request(path=base + query)[0], 404)

    def test_member_normalization_and_unknown_routes_are_refused(self):
        for path in (
            "/ops/members/x/unknown", "/ops/members/x/waiver/reset/", "/ops/members/x?",
            "/ops/members/x?before=1", "/ops/members/x/waiver/reset?before=1",
            "/ops/%6dembers/x", "//ops/members/x", "/ops//members/x",
            "/other/../ops/members/x", "/ops/members/x/../x", "/ops/members/%2e%2e/x",
            "/ops/members/x%2fy", "/ops/members/x%5cy", "/ops/members/x%252fy",
            "/ops/members/x%2540example.invalid", "/ops/members/x%00", "/ops/members/x%0d%0a",
        ):
            with self.subTest(path=path):
                self.assertIn(self.request(path=path)[0], (400, 404))
        for method in ("HEAD", "PUT", "DELETE", "OPTIONS", "get"):
            self.assertIn(self.request(path="/ops/members/x", method=method)[0], (400, 405))

    def test_isolated_status_is_token_free_and_strips_caller_identity(self):
        self.assertEqual(self.request(path="/ops/status")[0], 200)
        status, data = self.request(path="/ops/status", extra="Authorization: fixture-credential\r\nX-Joyride-Trusted-Test: forged\r\nTailscale-User-Login: forged\r\nForwarded: forged\r\n")
        self.assertEqual(status, 200)
        self.assertNotIn(b"fixture-credential", data)
        self.assertNotIn(b"forged", data)

    def test_exact_ops_methods_and_targets(self):
        for path in ("/ops/status?x=1", "/ops/status?", "/ops/%73tatus", "/ops/../ops/status", "//ops/status", "/ops//status"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path=path)[0], 404)
        self.assertEqual(self.request(path="/ops/status", method="POST")[0], 405)
        self.assertEqual(self.request(path="/ops/deploy")[0], 405)
        self.assertEqual(self.request(path="/ops/deploy", method="POST")[0], 200)

    def test_forwarded_headers_are_replaced(self):
        status, data = self.request(extra="Forwarded: host=other.invalid\r\nX-Forwarded-Proto: http\r\nX-Forwarded-Host: other.invalid\r\nX-Forwarded-For: 1.2.3.4\r\n")
        self.assertEqual(status, 200)
        self.assertIn(b'"Host": "joyride-test.eyrie"', data)
        self.assertIn(b'"X-Forwarded-Proto": "https"', data)
        self.assertNotIn(b"other.invalid", data)
        self.assertNotIn(b"1.2.3.4", data)


class RouterBoundary(unittest.TestCase):
    def test_snat_cannot_admit_router_local_or_other_forwarded_sources(self):
        guard = (ROOT / "files/tailscale/luna-gitlab.nft").read_text()
        output = guard.split("chain output {", 1)[1].split("}", 1)[0]
        self.assertIn("ip daddr 172.21.1.3 counter drop", output)
        forward = guard.split("chain forward {", 1)[1].split("}", 1)[0]
        allowed = 'iifname "tailscale0" ip saddr 100.127.2.74 ip daddr 172.21.1.3 tcp dport 443 counter return'
        denied = "ip daddr 172.21.1.3 counter drop"
        self.assertLess(forward.index(allowed), forward.index(denied))
        self.assertEqual(forward.count("ip daddr 172.21.1.3"), 2)

    def test_tailnet_grants_exact_destinations_only(self):
        policy = json.loads((ROOT / "files/tailscale/luna-gitlab.json").read_text())
        self.assertEqual(policy["acls"], [])
        self.assertEqual(policy["ssh"], [])
        self.assertEqual(policy["autoApprovers"], {})
        self.assertEqual(policy["grants"], [
            {"src": ["tag:luna-gitlab"], "dst": ["172.21.2.1/32"], "ip": ["tcp:22"]},
            {"src": ["tag:luna-gitlab"], "dst": ["172.21.1.3/32"], "ip": ["tcp:443"]},
        ])

    def test_firewalld_matches_tailnet_without_broad_accept(self):
        policy = ET.parse(ROOT / "files/tailscale/luna-gitlab.xml").getroot()
        self.assertEqual(policy.attrib["target"], "DROP")
        accepted = set()
        masqueraded = set()
        for rule in policy.findall("rule"):
            source = rule.find("source")
            target = rule.find("destination")
            assert source is not None and target is not None
            self.assertEqual(source.attrib["address"], "100.127.2.74/32")
            destination = target.attrib["address"]
            if rule.find("accept") is not None:
                port = rule.find("port")
                assert port is not None
                self.assertEqual(port.attrib["protocol"], "tcp")
                accepted.add((destination, port.attrib["port"]))
            elif rule.find("masquerade") is not None:
                masqueraded.add(destination)
            else:
                self.fail("Unexpected firewall rule")
        self.assertEqual(accepted, {("172.21.2.1/32", "22"), ("172.21.1.3/32", "443")})
        self.assertEqual(masqueraded, {"172.21.2.1/32", "172.21.1.3/32"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
