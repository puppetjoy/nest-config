#!/usr/bin/env python3
"""Refresh Kestrel's home DNS record without disclosing its CloudNS Dynamic URL.

The URL is a root-only eyaml-backed file, never a command argument. CloudNS
returns `OK` for a successful default-format update (including no change).
Run at boot and every five minutes via cloudns-home-update.timer.
"""

import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    try:
        url = Path('/etc/nest/cloudns-home.url').read_text().strip()
        parts = urlsplit(url)
        if (parts.scheme != 'https' or parts.netloc != 'ipv4.cloudns.net'
                or parts.path != '/api/dynamicURL/'
                or set(parse_qs(parts.query)) != {'q'}):
            raise ValueError('Invalid private URL')
        opener = build_opener(NoRedirect)
        for attempt in range(3):
            try:
                with opener.open(Request(url), timeout=8) as response:
                    if response.status == 200 and response.read(256).strip() == b'OK':
                        print('CloudNS home DNS update succeeded')
                        return 0
            except Exception:
                pass  # HTTP exceptions may contain the secret URL; never print them.
            if attempt < 2:
                time.sleep(2)
    except Exception:
        pass  # File/URL errors may contain secret data; emit only fixed text.
    print('CloudNS home DNS update failed', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
