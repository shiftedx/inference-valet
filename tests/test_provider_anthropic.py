"""Native Anthropic traffic must keep its semantics through Valet's profile router."""
import gc
import http.client
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

from ai_provider import make_server
from ai_provider_runtime import ProfileRouter


def event(kind, **fields):
    return ('event: '+kind+'\ndata: '+json.dumps(dict(type=kind, **fields))+'\n\n').encode()


class NativeBackend(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.server.requests.append((self.path, dict(self.headers), body))
        if self.path.endswith('/count_tokens'):
            response = {'input_tokens': 12345}
        elif self.path == '/v1/responses':
            response = {'object': 'response', 'model': 'native', 'output': []}
        else:
            response = dict(id='msg_fixture', type='message', role='assistant', model='native',
                            content=[dict(type='tool_use', id='toolu_fixture', name='read_file', input={'path': 'a.py'})],
                            stop_reason='tool_use', stop_sequence=None,
                            usage=dict(input_tokens=11, output_tokens=17, cache_read_input_tokens=5))
        if self.server.fail:
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Retry-After', '7')
            self.send_header('request-id', 'native-request')
            self.end_headers()
            self.wfile.write(b'{"type":"error","error":{"type":"rate_limit_error","message":"Retry later"}}')
        elif body.get('stream'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('request-id', 'native-stream')
            self.end_headers()
            self.wfile.write(event('message_start', message={**response, 'content': [], 'stop_reason': None}))
            self.wfile.write(event('ping'))
            self.wfile.flush()
            self.server.stream_started.set()
            self.server.release_stream.wait(5)
            self.wfile.write(event('content_block_start', index=0, content_block=dict(type='tool_use', id='toolu_fixture', name='read_file', input={})))
            self.wfile.write(event('content_block_delta', index=0, delta=dict(type='input_json_delta', partial_json='{"path":"a.py"}')))
            self.wfile.write(event('content_block_stop', index=0))
            self.wfile.write(event('message_delta', delta=dict(stop_reason='tool_use', stop_sequence=None), usage=dict(output_tokens=17)))
            self.wfile.write(event('message_stop'))
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())


class AnthropicProviderTests(unittest.TestCase):
    def setUp(self):
        gc.collect()  # Destroy prior Tk test fixtures on the main thread.
        self.profiles = {k: dict(label=k, context=131072, slots=1, engine=engine, model='native')
                         for k, engine in [('s', 'strata'), ('i', 'infernix'), ('n', 'ninfer'), ('g', 'llamacpp')]}
        self.current = 's'
        self.loader = Mock(side_effect=self.load)
        self.router = ProfileRouter(lambda _: self.current, self.loader)
        self.backend = self.start(ThreadingHTTPServer(('127.0.0.1', 0), NativeBackend))
        self.backend.requests = []
        self.backend.fail = False
        self.backend.stream_started = threading.Event()
        self.backend.release_stream = threading.Event()
        self.backend.release_stream.set()
        self.issues = []
        self.api = self.start(make_server('fixture', lambda: self.profiles, self.router.active,
            port=0, backend_port=self.backend.server_port, router=self.router,
            diagnostics=lambda *args, **fields: self.issues.append(fields)))

    def start(self, server):
        threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def load(self, key):
        self.current = key
        return {}

    def open(self, path='/v1/messages', body=None, headers=None, method='POST'):
        conn = http.client.HTTPConnection('127.0.0.1', self.api.server_port, timeout=5)
        self.addCleanup(conn.close)
        fields = {'x-api-key': 'fixture', 'anthropic-version': '2023-06-01', **(headers or {})}
        conn.request(method, path, body=json.dumps(body or {'model': 's', 'max_tokens': 50, 'messages': []}), headers=fields)
        return conn.getresponse()

    def test_native_payloads_headers_and_model_alias_across_backends(self):
        content = [dict(type='image', source=dict(type='base64', media_type='image/png', data='fixture')),
                   dict(type='tool_result', tool_use_id='toolu_previous', content='contents', is_error=True)]
        for profile in self.profiles:
            body = dict(model=profile, max_tokens=32768, system=[dict(type='text', text='system', cache_control={'type': 'ephemeral'})],
                        messages=[dict(role='user', content=content)],
                        tools=[dict(name='read_file', input_schema={'type': 'object'})],
                        thinking={'type': 'enabled', 'budget_tokens': 8192}, output_config={'effort': 'high'})
            response = self.open('/v1/messages?beta=true', body, {'anthropic-beta': 'tools-fixture', 'Connection': 'close'})
            self.assertEqual(response.status, 200)
            result = json.load(response)
            self.assertEqual(result['model'], profile)
            self.assertEqual(result['stop_reason'], 'tool_use')
            self.assertEqual(result['content'][0]['input'], {'path': 'a.py'})
            path, headers, forwarded = self.backend.requests[-1]
            self.assertEqual(path, '/v1/messages')
            self.assertEqual(forwarded, {**body, 'model': 'native'})
            self.assertEqual(headers['anthropic-beta'], 'tools-fixture')
            self.assertEqual(headers['anthropic-version'], '2023-06-01')
            self.assertEqual(headers['Authorization'], 'Bearer fixture')
            self.assertNotIn('x-api-key', headers)
        self.assertEqual(self.loader.call_count, 3)

    def test_token_count_and_v1_base_aliases(self):
        for profile in self.profiles:
            for path in ['/v1/messages/count_tokens', '/v1/v1/messages/count_tokens']:
                response = self.open(path, {'model': profile, 'messages': []})
                self.assertEqual(response.status, 200)
                self.assertEqual(json.load(response), {'input_tokens': 12345})
                self.assertEqual(self.backend.requests[-1][0], '/v1/messages/count_tokens')
        response = self.open('/v1/v1/messages')
        self.assertEqual(response.status, 200)
        self.assertEqual(json.load(response)['model'], 's')

    def test_stream_is_incremental_and_holds_router_until_message_stop(self):
        self.backend.release_stream.clear()
        self.addCleanup(self.backend.release_stream.set)
        response = self.open(body={'model': 's', 'stream': True, 'max_tokens': 50, 'messages': []})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader('request-id'), 'native-stream')
        self.assertEqual(response.readline(), b'event: message_start\n')
        self.assertEqual(json.loads(response.readline()[6:])['message']['model'], 's')
        self.assertEqual(response.readline(), b'\n')
        self.assertEqual(response.readline(), b'event: ping\n')
        self.assertEqual(self.router.inflight, 1)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(lambda: self.open(body={'model': 'i'}).read())
            with self.router.condition:
                self.assertTrue(self.router.condition.wait_for(lambda: bool(self.router.queue), timeout=2))
            self.loader.assert_not_called()
            self.backend.release_stream.set()
            remaining = response.read()
            self.assertIn(b'input_json_delta', remaining)
            self.assertIn(b'event: message_delta', remaining)
            self.assertTrue(remaining.endswith(event('message_stop')))
            self.assertEqual(json.loads(future.result(timeout=3))['model'], 'i')
        self.assertEqual(self.router.inflight, 0)

    def test_anthropic_errors_authentication_and_unknown_models_do_not_load(self):
        for headers, body, code, kind in [
            ({'x-api-key': 'wrong'}, {'model': 's'}, 401, 'authentication_error'),
            ({}, {'model': 'missing'}, 404, 'not_found_error'),
            ({}, {'model': 4}, 400, 'invalid_request_error')]:
            response = self.open(body=body, headers=headers)
            self.assertEqual(response.status, code)
            result = json.load(response)
            self.assertEqual(result['type'], 'error')
            self.assertEqual(result['error']['type'], kind)
            self.assertEqual(result['request_id'], response.getheader('X-Request-ID'))
        self.loader.assert_not_called()
        self.assertFalse(self.backend.requests)

    def test_bearer_auth_and_discovery_keep_existing_profile_metadata(self):
        response = self.open('/v1/models?limit=1000', headers={'x-api-key': '', 'Authorization': 'Bearer fixture'}, method='GET')
        models = json.load(response)
        self.assertFalse(models['has_more'])
        self.assertEqual(models['first_id'], 's')
        self.assertEqual(models['last_id'], 'g')
        self.assertEqual(models['data'][0]['display_name'], 's')
        self.assertEqual(models['data'][0]['context_length'], 131072)
        self.assertFalse(self.backend.requests)
        response = self.open('/v1/responses', {'model': 'g', 'input': 'hello'})
        self.assertEqual(response.status, 200)
        self.assertEqual(json.load(response)['model'], 'g')
        self.assertEqual(self.backend.requests[-1][0], '/v1/responses')

    def test_backend_errors_and_retry_headers_are_preserved(self):
        self.backend.fail = True
        response = self.open()
        self.assertEqual(response.status, 429)
        self.assertEqual(response.getheader('Retry-After'), '7')
        self.assertEqual(response.getheader('request-id'), 'native-request')
        self.assertEqual(json.load(response)['error']['type'], 'rate_limit_error')

    def test_load_failures_are_anthropic_errors_and_do_not_leak_exception_text(self):
        self.loader.side_effect = RuntimeError('private credential material')
        response = self.open(body={'model': 'i'})
        self.assertEqual(response.status, 503)
        result = json.load(response)
        self.assertEqual(result['error']['type'], 'api_error')
        self.assertNotIn('private', json.dumps(result))
        self.assertFalse(self.backend.requests)

    def test_official_sdk_messages_stream_and_token_count(self):
        try:
            import anthropic
        except ImportError:
            self.skipTest('Optional anthropic SDK is not installed')
        with anthropic.Anthropic(base_url=f'http://127.0.0.1:{self.api.server_port}',
                                 api_key='fixture', max_retries=0, timeout=5) as client:
            messages = [dict(role='user', content='Read a.py')]
            result = client.messages.create(model='s', max_tokens=50, messages=messages)
            self.assertEqual(result.model, 's')
            self.assertEqual(result.content[0].input, {'path': 'a.py'})
            self.assertEqual(client.messages.count_tokens(model='s', messages=messages).input_tokens, 12345)
            with client.messages.stream(model='i', max_tokens=50, messages=messages) as stream:
                result = stream.get_final_message()
            self.assertEqual(result.model, 'i')
            self.assertEqual(result.stop_reason, 'tool_use')
            self.assertEqual(result.content[0].input, {'path': 'a.py'})
            self.assertEqual(result.usage.output_tokens, 17)

    def test_anthropic_malformed_and_oversized_bodies_are_redacted(self):
        for data, headers, status, reason in [
            (b'{"secret":"DO_NOT_LOG",broken}', {}, 400, 'invalid_json'),
            (b'{}', {'Content-Length': str(64*1024*1024+1)}, 413, 'body_too_large')]:
            conn = http.client.HTTPConnection('127.0.0.1', self.api.server_port, timeout=5)
            self.addCleanup(conn.close)
            conn.request('POST', '/v1/messages', body=data, headers={'x-api-key': 'fixture', **headers})
            response = conn.getresponse()
            self.assertEqual(response.status, status)
            self.assertEqual(json.load(response)['type'], 'error')
            self.assertEqual(self.issues[-1]['reason'], reason)
            self.assertNotIn('DO_NOT_LOG', json.dumps(self.issues))
        self.assertFalse(self.backend.requests)


if __name__ == '__main__':
    unittest.main()
