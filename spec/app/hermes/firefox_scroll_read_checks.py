"""Synthetic-only extensions to the real public TLS/native workflow canary."""
import json
import os
import time


def fixture_body(path):
    if not path.startswith('/scroll-read'):
        return None
    nested = 'nested' in path
    style = 'html,body{height:100%;overflow:hidden}' if nested else ''
    position = 'sticky' if 'sticky' in path else 'fixed'
    return ('''<title>Scroll read fixture</title><style>body{margin:0}''' + style + '''
    #header{position:''' + position + ''';left:0;top:0;width:100%;height:64px;background:#ddf;z-index:8}
    #pane{margin:80px 8%;height:400px;overflow:auto;border:2px solid blue}
    .content{height:4000px;background:linear-gradient(white,green)}
    </style><div id="header">Fixed non-scrolling header</div><div id="pane"><div class="content">Nested content</div></div>
    ''' + ('' if nested else '<div class="content">Root content</div>') + '''
    <pre id="long"></pre><script>
    document.querySelector('#header').addEventListener('wheel',e=>e.preventDefault(),{passive:false});
    document.querySelector('#long').textContent='A'.repeat(3995)+' user@example.invalid '+'B'.repeat(16000);
    document.addEventListener('scroll',e=>fetch('/observe',{method:'POST',body:JSON.stringify({root:scrollY,pane:document.querySelector('#pane').scrollTop})}),true);
    </script>''').encode()


def run(engine, call, base, emit, requests, endpoint=None):
    scope = 'kanban:canary:t_publicfixture'
    cid = engine.state['windows'][scope]['context']
    def geometry():
        return engine._evaluate(cid, '({root:scrollY,pane:document.querySelector("#pane").scrollTop,width:innerWidth,height:innerHeight})', read_only=True)
    mode = os.environ.get('FIREFOX_SCROLL_READ_MODE', 'all')
    if mode in {'all', 'scroll'}:
        call('navigate', {'url': base + '/scroll-read-root'})
        before = geometry()
        result = call('scroll', {'direction': 'down', 'amount': 1})
        time.sleep(.3)
        after = geometry()
        emit('scroll-fixed-header', before=before, after=after, result=result.get('scroll'))
        assert after['root'] > before['root'], 'public scroll acknowledged but root did not move beneath fixed wheel-cancelling header'
        assert result['scroll']['outcome'] == 'moved'
        call('scroll', {'direction': 'up', 'amount': 10})
        time.sleep(.3)
        boundary = call('scroll', {'direction': 'up', 'amount': 1})
        assert boundary['scroll']['outcome'] == 'at_boundary', boundary
        call('scroll', {'direction': 'down', 'amount': 10})
        time.sleep(.3)
        boundary = call('scroll', {'direction': 'down', 'amount': 10})
        assert boundary['scroll']['outcome'] == 'at_boundary', boundary
        call('navigate', {'url': base + '/scroll-read-root-sticky'})
        before = geometry()
        assert call('scroll', {'direction': 'down', 'amount': 1})['scroll']['outcome'] == 'moved'
        assert geometry()['root'] > before['root']
        assert any(r.get('observation', {}).get('root', 0) > 0 for r in requests if r.get('observation'))
        # Real event cancellation must be reported as no movement, not replayed
        # at another point or silently replaced by script scrolling.
        time.sleep(.3)
        engine._evaluate(cid, 'document.addEventListener("wheel",e=>e.preventDefault(),{passive:false});true')
        before = geometry()
        canceled = call('scroll', {'direction': 'down', 'amount': 1})
        assert canceled['scroll']['outcome'] == 'no_movement' and geometry() == before, canceled
        call('navigate', {'url': base + '/scroll-read-nested'})
        before = geometry()
        result = call('scroll', {'direction': 'down', 'amount': 1})
        time.sleep(.3)
        after = geometry()
        assert after['pane'] > before['pane'] and after['root'] == before['root'], (before, after, result)
        assert result['scroll']['outcome'] == 'moved'
        call('scroll', {'direction': 'up', 'amount': 10})
        # Native resizing changes hit-testing; no source-fixed viewport point.
        engine._call('browsingContext.setViewport', {'context': cid, 'viewport': {'width': 720, 'height': 600}})
        result = call('scroll', {'direction': 'down', 'amount': 1})
        assert result['scroll']['outcome'] == 'moved', result
        emit('scroll-pass', root=True, nested=True, boundaries=True, resized=True, sticky=True, cancellation=True, server_observed=True)
        engine._call('browsingContext.setViewport', {'context': cid, 'viewport': None})
    if mode in {'all', 'read'}:
        call('navigate', {'url': base + '/scroll-read-root'})
        expression = 'document.readText("#long",0)'
        first = call('query', {'expression': expression})
        assert first['nextCursor'] and not first['complete'], first
        pages = [first['value']['text']]
        current = first
        while current['nextCursor']:
            current = call('query', {'expression': expression, 'cursor': current['nextCursor']})
            pages.append(current['value']['text'])
            assert len(pages) < 20
        text = ''.join(pages)
        assert 'user@example.invalid' not in text and '<redacted>' in text
        assert len(text) == current['value']['totalChars']
        engine._evaluate(cid, 'document.querySelector("#long").textContent+=" dynamic change";true')
        stale = call('query', {'expression': expression, 'cursor': first['nextCursor']}, ('error',))
        emit('stale-read', error=stale.get('error'), outcome=stale.get('outcome'))
        assert stale['error'] == 'FIREFOX_TEXT_CURSOR_STALE' and stale['outcome'] == 'not_started', stale
        restart = call('query', {'expression': expression})
        assert restart['value']['offset'] == 0 and restart['revision'] != first['revision']
        assert restart['nextCursor']
        assert not engine.state['actions'].get('read')
        before_actions = json.dumps(engine.state['actions'], sort_keys=True)
        native = engine.browser._bidi
        faulted = []
        def lose_observation(method, params, **kwargs):
            result = native(method, params, **kwargs)
            if method == 'script.evaluate' and not faulted:
                faulted.append(True)
                raise TimeoutError('synthetic observation acknowledgement lost')
            return result
        engine.browser._bidi = lose_observation
        failed = call('query', {'expression': expression, 'cursor': restart['nextCursor']}, ('error',))
        assert failed['error'] == 'FIREFOX_NATIVE_OUTCOME_UNCERTAIN' and failed['operation'] == 'query', failed
        assert faulted == [True]
        recovered = call('query', {'expression': expression})
        assert recovered['value']['offset'] == 0
        if endpoint is not None:
            import socket
            original_reply = endpoint.Handler.reply
            interrupted = []
            def drop_read(handler, code, value):
                if value.get('revision') and not interrupted:
                    interrupted.append(True)
                    handler.connection.shutdown(socket.SHUT_RDWR)
                    handler.connection.close()
                    return
                return original_reply(handler, code, value)
            endpoint.Handler.reply = drop_read
            try:
                failed = call('query', {'expression': expression, 'cursor': recovered['nextCursor']}, ('error',))
                assert failed['operation'] == 'query' and failed['outcome'] == 'uncertain', failed
            finally:
                endpoint.Handler.reply = original_reply
            assert interrupted == [True]
            assert call('query', {'expression': expression})['value']['offset'] == 0
        assert json.dumps(engine.state['actions'], sort_keys=True) == before_actions
        emit('read-pass', pages=len(pages), redacted=True, stale_typed=True, restart=True, native_timeout=True, interrupted_http=True, input_journal_unchanged=True)
