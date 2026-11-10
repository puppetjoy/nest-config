#!/usr/bin/env python3
"""Reconcile only the bounded router preferences, without enrollment or secrets."""
import json
import subprocess
import sys

EXPECTED = {
    "RouteAll": False,
    "CorpDNS": False,
    "RunSSH": False,
    "RunWebClient": False,
    "NoSNAT": False,
    "NetfilterMode": 0,
    "AdvertiseRoutes": ["172.21.0.3/32", "172.21.1.3/32", "172.21.2.1/32"],

    "ExitNodeID": "",
    "ExitNodeIP": "",
    "ExitNodeAllowLANAccess": False,
}


def converged():
    result = subprocess.run(
        ["/usr/sbin/tailscale", "debug", "prefs"],
        check=True, capture_output=True, text=True,
    )
    prefs = json.loads(result.stdout)
    return all(prefs.get(key) == value for key, value in EXPECTED.items())


def main():
    if sys.argv[1:] == ["--check"]:
        return 0 if converged() else 1
    if sys.argv[1:]:
        return 2
    subprocess.run([
        "/usr/sbin/tailscale", "set",
        "--accept-dns=false", "--accept-routes=false", "--ssh=false",
        "--webclient=false",
        "--advertise-exit-node=false", "--exit-node=",
        "--exit-node-allow-lan-access=false", "--snat-subnet-routes=true",
        "--netfilter-mode=off", "--advertise-routes=172.21.0.3/32,172.21.1.3/32,172.21.2.1/32",

    ], check=True, capture_output=True, text=True)
    return 0 if converged() else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (subprocess.CalledProcessError, ValueError):
        # Never forward daemon output, which can include enrollment URLs.
        print("Tailscale preference reconciliation failed", file=sys.stderr)
        sys.exit(1)
