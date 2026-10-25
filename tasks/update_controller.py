#!/usr/bin/env python3
"""Check the existing external Bolt execution host; never dispatch a host action."""
import json
import os
import socket
import sys


def main():
    try:
        p = json.loads(sys.stdin.read(4097))
        # The Nest wrapper sets this from its actual host, not from request data.
        # Direct native Bolt uses its own hostname. This is ordinary operator
        # coordination, not cryptographic machine attestation.
        actual = os.environ.get('NEST_BOLT_CONTROLLER', socket.gethostname())
        expected = p['controller']
        if type(expected) is not str or actual != expected:
            raise ValueError('wrong controller')
        print(json.dumps({'controller': actual, 'controller_observed': True}))
        return 0
    except (KeyError, TypeError, ValueError):
        print(json.dumps({'_error': {'kind': 'nest/update-controller', 'msg': 'Run the lifecycle on the reviewed surviving external controller'}}))
        return 1


if __name__ == '__main__':
    sys.exit(main())
