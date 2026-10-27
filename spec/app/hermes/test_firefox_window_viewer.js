// Owner viewer key bursts serialize once, never drop keys or retry uncertainty.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

// Execute the resident's actual fixed guard, not a copy of its selector logic.
function targetGuards() {
  const source = fs.readFileSync(path.resolve(__dirname, '../../../files/firefox-browser/firefox_windows.py'), 'utf8');
  const declaration = source.match(/ELEMENT = """([\s\S]*?)"""/)[1];
  const element = (width = 24, visibility = 'visible') => ({
    getBoundingClientRect: () => ({left: 10, top: 20, width, height: width}),
    style: {visibility, display: 'flex'}, disabled: false, contains: () => false,
    getAttribute: () => '', matches: () => false
  });
  const visible = element(), hidden = element(0), collapsed = element(24, 'hidden');
  let matches = [hidden, visible, collapsed], hit = visible;
  const guard = vm.runInNewContext('(' + declaration + ')', {
    document: {querySelectorAll: () => matches, elementFromPoint: () => hit},
    getComputedStyle: e => e.style, innerWidth: 500, innerHeight: 497
  });
  assert.equal(guard('button', 0, 0).node, visible);
  matches = [visible, element()];
  assert.throws(() => guard('button', 0, 0), /target is not unique/);
  matches = [hidden, collapsed];
  assert.throws(() => guard('button', 0, 0), /target is not unique/);
  matches = [visible];
  hit = element();
  assert.throws(() => guard('button', 0, 0), /intercepted/);
  hit = visible;
  visible.disabled = true;
  assert.throws(() => guard('button', 0, 0), /target unavailable/);
  visible.disabled = false;
  assert.equal(guard(null, 12, 25).node, visible);
}

async function run(failInput = false) {
  const listeners = {};
  const requests = [];
  const canvas = {addEventListener: (name, fn) => { listeners[name] = fn; }, focus() {},
    getBoundingClientRect: () => ({left: 0, top: 0, width: 800, height: 600}),
    getContext: () => ({drawImage() {}}), style: {}};
  const status = {textContent: ''};
  const refresh = {addEventListener() {}};
  const sandbox = {
    location: {hash: '#synthetic-window-capability'},
    document: {getElementById: id => id === 'view' ? canvas : id === 'status' ? status : refresh},
    AbortSignal, setInterval() {},
    Image: class {constructor() { this.width = 800; this.height = 600; } set src(value) { this.onload(); }},
    fetch: async (url, options) => {
      const body = JSON.parse(options.body);
      requests.push({url, options, body});
      if (failInput && body.command === 'input') throw new Error('Synthetic uncertain delivery');
      return {ok: true, json: async () => ({status: 'ok', png_base64: 'fixture'})};
    }
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.resolve(__dirname, '../../../files/firefox-browser/window-viewer.js'), 'utf8'), sandbox);
  // Queue a key burst while the initial screenshot promise is still in flight.
  for (const key of 'abcdefghij') listeners.keydown({key, preventDefault() {}});
  await vm.runInContext('inputs', sandbox);
  const input = requests.filter(request => request.body.command === 'input');
  if (!failInput) {
    assert.equal(input.map(request => request.body.payload.key).join(''), 'abcdefghij');
    assert.equal(vm.runInContext('pending', sandbox), 0);
    listeners.wheel({clientX: 100, clientY: 200, deltaMode: 1, deltaX: 0, deltaY: 300, preventDefault() {}});
    await vm.runInContext('inputs', sandbox);
    const wheel = requests.filter(request => request.body.payload?.kind === 'scroll');
    assert.equal(wheel.length, 1);
    assert.deepEqual(wheel[0].body.payload, {kind: 'scroll', x: 100, y: 200, deltaX: 0, deltaY: 2000});
  } else {
    assert.equal(input.length, 1);  // No automatic replay or later buffered input.
    assert.equal(vm.runInContext('inputFailed', sandbox), true);
    listeners.keydown({key: 'z', preventDefault() {}});
    await vm.runInContext('inputs', sandbox);
    assert.equal(requests.filter(request => request.body.command === 'input').length, 1);
  }
  for (const request of requests) {
    assert.equal(request.options.credentials, 'omit');
    assert.equal(request.options.redirect, 'error');
    assert.equal(request.options.headers.Authorization, 'Window synthetic-window-capability');
    assert.equal(request.url, '/_nest/bridge/window/control');
    assert.equal(Object.hasOwn(request.body, 'scope'), false);
  }
}
(async () => { targetGuards(); await run(); await run(true); console.log('Firefox target guard and window viewer regressions passed'); })().catch(error => { console.error(error); process.exitCode = 1; });
