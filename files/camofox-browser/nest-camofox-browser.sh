#!/bin/sh
set -eu

export CAMOFOX_HOST="${CAMOFOX_HOST:-0.0.0.0}"
export CAMOFOX_PORT="${CAMOFOX_PORT:-9377}"
export CAMOFOX_DATA_DIR="${CAMOFOX_DATA_DIR:-/home/node/.camofox}"
export CAMOFOX_AUTH_MODE="${CAMOFOX_AUTH_MODE:-disabled}"
export HOME="${HOME:-/home/node}"

mkdir -p "${CAMOFOX_DATA_DIR}" "${HOME}"

if [ "${CAMOFOX_IGNORE_HTTPS_ERRORS:-false}" = "true" ]; then
  node <<'JS'
const fs = require('node:fs');
const candidates = [
  '/usr/lib64/node_modules/camofox-browser/dist/src/services/context-pool.js',
];
for (const path of candidates) {
  if (!fs.existsSync(path)) continue;
  let text = fs.readFileSync(path, 'utf8');
  const marker = 'downloadsPath: CONFIG.downloadsDir,';
  if (text.includes(marker) && !text.includes('ignoreHTTPSErrors: true,')) {
    text = text.replace(marker, `${marker}\n                ignoreHTTPSErrors: true,`);
    fs.writeFileSync(path, text);
    console.warn('[nest] Camofox trusted-internal HTTPS errors ignored for this pod');
    break;
  }
}
JS
fi

if [ -n "${CAMOFOX_SCREEN_WIDTH:-}" ] && [ -n "${CAMOFOX_SCREEN_HEIGHT:-}" ]; then
  node <<'JS'
const fs = require('node:fs');
const path = '/usr/lib64/node_modules/camofox-browser/dist/src/services/context-pool.js';
if (fs.existsSync(path)) {
  let text = fs.readFileSync(path, 'utf8');
  const marker = '            const opts = await (0, camoufox_js_1.launchOptions)({';
  const shim = [
    '            const requestedScreen = (contextOptions && contextOptions.viewport) ? contextOptions.viewport : CONFIG.fingerprintDefaults.screen;',
    '            if (requestedScreen && fingerprint && fingerprint.screen) {',
    '                const { width, height } = requestedScreen;',
    '                Object.assign(fingerprint.screen, {',
    '                    width,',
    '                    height,',
    '                    availWidth: width,',
    '                    availHeight: height,',
    '                    outerWidth: width,',
    '                    outerHeight: height + 61,',
    '                    innerWidth: width,',
    '                    innerHeight: height,',
    '                    clientWidth: width,',
    '                    clientHeight: height,',
    '                });',
    '            }',
    '',
  ].join('\n');
  if (text.includes(marker) && !text.includes('const requestedScreen = (contextOptions && contextOptions.viewport)')) {
    text = text.replace(marker, `${shim}${marker}`);
    fs.writeFileSync(path, text);
    console.warn('[nest] Camofox fingerprint screen metrics pinned for this pod');
  }
}
JS
fi

if [ -n "${CAMOFOX_CONTEXT_CLOSE_TIMEOUT_MS:-}" ]; then
  node <<'JS'
const fs = require('node:fs');
const path = '/usr/lib64/node_modules/camofox-browser/dist/src/services/context-pool.js';
if (fs.existsSync(path)) {
  let text = fs.readFileSync(path, 'utf8');
  const marker = '            await entry.context?.close().catch(() => { });';
  const shim = [
    '            const closeTimeoutMs = Number(process.env.CAMOFOX_CONTEXT_CLOSE_TIMEOUT_MS || 10000);',
    '            const closePromise = entry.context?.close().catch(() => { });',
    '            if (closePromise && Number.isFinite(closeTimeoutMs) && closeTimeoutMs > 0) {',
    '                let timeout;',
    '                await Promise.race([',
    '                    closePromise.finally(() => clearTimeout(timeout)),',
    '                    new Promise((resolve) => { timeout = setTimeout(resolve, closeTimeoutMs); }),',
    '                ]);',
    '            } else {',
    '                await closePromise;',
    '            }',
  ].join('\n');
  if (text.includes(marker) && !text.includes('CAMOFOX_CONTEXT_CLOSE_TIMEOUT_MS')) {
    text = text.replace(marker, shim);
    fs.writeFileSync(path, text);
    console.warn('[nest] Camofox context close timeout bounded for this pod');
  }
}
JS
fi

exec camofox-browser "$@"
