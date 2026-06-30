#!/bin/bash
# Patch camofox-browser server.js to strip isMobile from viewport
# before it reaches the Camoufox CDP layer.
# See ar-20260630-233757-a80b42.

set -euo pipefail

SERVER_JS='/usr/lib64/node_modules/@askjo/camofox-browser/server.js'

if [ ! -f "$SERVER_JS" ]; then
  echo "INFO: $SERVER_JS not found, skipping viewport patch"
  exit 0
fi

# Strip isMobile from contextOptions.viewport before newContext()
sed -i '/b\.newContext(contextOptions)/i\
  if (contextOptions.viewport) delete contextOptions.viewport.isMobile;' "$SERVER_JS"

echo "PATCHED: stripped isMobile from viewport in $SERVER_JS"
