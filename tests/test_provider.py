import gc
import http.client
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ai_provider import make_server
from ai_provider_runtime import ProfileRouter, ProfileUnavailable


class Backend(BaseHTTPRequestHandler):
    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((self.path, self.headers["Authorization"], payload))
        self.send_response(200)
        if payload.get("stream"):
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'event: response.created\ndata: {"response":{"model":"native"}}\n\ndata: [DONE]\n\n')
        else:
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"model":"native","choices":[]}')


class ProviderTests(unittest.TestCase):
    def setUp(self):
        # Collect prior Tk fixtures on the main thread before HTTP workers run.
        gc.collect()
        self.profiles = {
            "coding-128k": dict(label="Coding", context=131072, slots=3, engine="strata",
                                model="native", default_max_output_tokens=32768),
            "coding-256k": dict(label="Long context", context=262144, slots=1, engine="strata",
                                model="native"),
            "other": dict(label="Other backend", context=98304, slots=1, engine="infernix", model="other"),
        }
        self.backend = self.start(ThreadingHTTPServer(("127.0.0.1", 0), Backend))
        self.backend.requests = []
        self.ingress_events = []
        self.api = self.start(make_server("fixture", lambda: self.profiles,
                                          lambda _: "coding-128k", port=0,
                                          backend_port=self.backend.server_port,
                                          diagnostics=lambda *args, **details: self.ingress_events.append(details)))

    def start(self, server):
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def request(self, path, body=None, key="fixture"):
        headers = {"Authorization": "Bearer " + key}
        data = None if body is None else json.dumps(body).encode()
        req = Request(f"http://127.0.0.1:{self.api.server_port}/v1{path}", data=data, headers=headers)
        with urlopen(req, timeout=5) as reply:
            return reply.read()

    def test_discovery_distinguishes_profiles_with_same_backend_model(self):
        result = json.loads(self.request("/models"))
        self.assertEqual(result["object"], "list")
        entries = {p["id"]: p for p in result["data"]}
        self.assertEqual(entries["coding-128k"]["context_length"], 131072)
        self.assertEqual(entries["coding-128k"]["parallel_slots"], 3)
        self.assertEqual(entries["coding-128k"]["default_max_output_tokens"], 32768)
        self.assertEqual(entries["coding-256k"]["context_length"], 262144)
        self.assertEqual(json.loads(self.request("/models/coding-256k")), entries["coding-256k"])
        self.assertFalse(self.backend.requests)

    def test_vision_discovery_and_image_parts_are_forwarded(self):
        self.profiles['coding-128k'].update(supports_vision=True, input_modalities=['text', 'image'])
        entries = {row['id']: row for row in json.loads(self.request('/models'))['data']}
        single = json.loads(self.request('/models/coding-128k'))
        self.assertEqual(single, entries['coding-128k'])
        self.assertTrue(single['supports_vision'])
        self.assertEqual(single['input_modalities'], ['text', 'image'])
        parts = [{'type': 'text', 'text': 'Describe this image'},
                 {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,fixture', 'detail': 'low'}}]
        messages = [{'role': 'user', 'content': parts}]
        self.request('/chat/completions', {'model': 'coding-128k', 'messages': messages})
        self.assertEqual(self.backend.requests[-1][2]['messages'], messages)

    def raw_request(self, body, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.api.server_port, timeout=5)
        connection.request('POST', '/v1/chat/completions', body=body,
                           headers={'Authorization': 'Bearer fixture', **(headers or {})})
        response = connection.getresponse()
        result = response.status, json.loads(response.read()), response.getheader('X-Request-ID')
        connection.close()
        return result

    def test_ingress_reasons_are_redacted_and_correlated(self):
        cases = [(b'{broken', {}, 'invalid_json'),
                 (b'{"model":17,"private":"DO_NOT_LOG"}', {}, 'invalid_model_field'),
                 (b'[]', {}, 'not_json_object'),
                 (b'{"model":"\xff"}', {}, 'invalid_utf8'),
                 (b'{}', {'Transfer-Encoding': 'chunked'}, 'unsupported_transfer_encoding'),
                 (b'{}', {'Content-Length': 'invalid'}, 'invalid_content_length')]
        for body, headers, reason in cases:
            with self.subTest(reason=reason):
                status, payload, request_id = self.raw_request(body, headers)
                self.assertEqual(status, 400)
                event = self.ingress_events[-1]
                self.assertEqual(event['reason'], reason)
                self.assertEqual(event['request_id'], request_id)
                self.assertNotIn('DO_NOT_LOG', json.dumps(event))
                self.assertNotIn('fixture', json.dumps(event))
        self.assertFalse(self.backend.requests)

    def test_body_limit_still_returns_413_before_routing(self):
        status, _, _ = self.raw_request(b'{}', {'Content-Length': str(64*1024*1024+1)})
        self.assertEqual(status, 413)
        self.assertEqual(self.ingress_events[-1]['reason'], 'body_too_large')
        self.assertEqual(self.ingress_events[-1]['body_bytes_received'], 0)
        self.assertFalse(self.backend.requests)

    def test_body_inactivity_timeout_is_distinguished_from_json(self):
        import socket
        setup = self.api.RequestHandlerClass.setup
        def short_setup(handler):
            setup(handler)
            handler.connection.settimeout(.1)
        self.api.RequestHandlerClass.setup = short_setup
        with socket.create_connection(('127.0.0.1', self.api.server_port), timeout=5) as connection:
            connection.sendall(b'POST /v1/chat/completions HTTP/1.0\r\nAuthorization: Bearer fixture\r\nContent-Length: 100\r\n\r\n{')
            response = connection.makefile('rb').read()
        self.assertIn(b'400 Bad Request', response)
        event = self.ingress_events[-1]
        self.assertEqual(event['reason'], 'body_read_timeout')
        self.assertEqual(event['body_bytes_declared'], 100)
        self.assertEqual(event['body_bytes_received'], 1)
        self.assertFalse(self.backend.requests)

    def test_missing_duplicate_and_incomplete_framing_are_diagnosed(self):
        import socket
        cases = [(b'', b'', 'missing_content_length'),
                 (b'Content-Length: 2\r\nContent-Length: 3\r\n', b'{}', 'invalid_content_length'),
                 (b'Content-Length: 100\r\n', b'{}', 'incomplete_body')]
        for framing, body, reason in cases:
            with self.subTest(reason=reason):
                with socket.create_connection(('127.0.0.1', self.api.server_port), timeout=5) as connection:
                    connection.sendall(b'POST /v1/chat/completions HTTP/1.0\r\nAuthorization: Bearer fixture\r\n' + framing + b'\r\n' + body)
                    connection.shutdown(socket.SHUT_WR)
                    response = connection.makefile('rb').read()
                self.assertIn(b'400 Bad Request', response)
                self.assertEqual(self.ingress_events[-1]['reason'], reason)
        self.assertEqual(self.ingress_events[-1]['body_bytes_received'], 2)
        self.assertFalse(self.backend.requests)

    def test_diagnostic_failure_does_not_replace_the_http_error(self):
        def unavailable_sink(*args, **details):
            raise OSError('private diagnostic failure')
        self.api = self.start(make_server('fixture', lambda: self.profiles, lambda _: 'coding-128k',
                                          port=0, backend_port=self.backend.server_port,
                                          diagnostics=unavailable_sink))
        status, payload, request_id = self.raw_request(b'{broken')
        self.assertEqual(status, 400)
        self.assertEqual(payload['error']['code'], 'invalid_request')
        self.assertTrue(request_id)
        self.assertNotIn('private', json.dumps(payload))
        self.assertFalse(self.backend.requests)

    def test_valid_twelve_megabyte_bodies_are_forwarded(self):
        for size in (12440216, 12448302):
            prefix = b'{"model":"coding-128k","messages":[],"fixture":"'
            suffix = b'"}'
            body = prefix + b'x'*(size-len(prefix)-len(suffix)) + suffix
            status, _, _ = self.raw_request(body)
            self.assertEqual(status, 200)
            self.assertEqual(len(self.backend.requests[-1][2]['fixture']), size-len(prefix)-len(suffix))
        self.assertFalse(self.ingress_events)

    def test_rejects_unauthorized_unknown_and_inactive_profiles(self):
        for path, body, key, status in [
            ("/models", None, "wrong", 401), ("/models/missing", None, "fixture", 404),
            ("/chat/completions", {"model": "coding-256k"}, "fixture", 503),
            ("/responses", {"model": "other"}, "fixture", 404),
        ]:
            with self.subTest(path=path, status=status), self.assertRaises(HTTPError) as exc:
                self.request(path, body, key)
            self.assertEqual(exc.exception.code, status)
            self.assertIn("error", json.load(exc.exception))
        self.assertFalse(self.backend.requests)

    def test_accepts_the_active_native_id_for_existing_clients(self):
        body = {"model": "native", "messages": []}
        result = json.loads(self.request("/chat/completions", body))
        self.assertEqual(result["model"], "native")
        self.assertEqual(self.backend.requests[0][2], body)

    def test_forwards_json_and_streaming_with_profile_alias(self):
        body = {"model": "coding-128k", "messages": [], "tools": [{"type": "function"}]}
        self.assertEqual(json.loads(self.request("/chat/completions", body))["model"], "coding-128k")
        path, auth, payload = self.backend.requests[0]
        self.assertEqual((path, auth, payload), ("/v1/chat/completions", "Bearer fixture", {**body, "model": "native"}))
        stream = self.request("/responses", {"model": "coding-128k", "stream": True})
        self.assertIn(b"event: response.created", stream)
        self.assertIn(b'"model": "coding-128k"', stream)
        self.assertIn(b"data: [DONE]", stream)


class DynamicProviderTests(ProviderTests):
    def setUp(self):
        super().setUp()
        self.current = None
        self.loads = []
        self.loader = Mock(side_effect=self.load)
        self.router = ProfileRouter(lambda _: self.current, self.loader)
        self.api = self.start(make_server('fixture', lambda: self.profiles, self.router.active,
                                          port=0, backend_port=self.backend.server_port, router=self.router,
                                          diagnostics=lambda *args, **details: self.ingress_events.append(details)))

    def load(self, key):
        self.loads.append(key)
        self.current = key
        return {'profile': key}

    # The base fixture exercises active-only compatibility; dynamic routing has
    # its own expectations for inactive profiles and ambiguous native aliases.
    def test_discovery_loaded_flags_change_without_loading_any_profile(self):
        self.current = 'coding-128k'
        first = {p['id']:p for p in json.loads(self.request('/models'))['data']}
        self.assertEqual([k for k,p in first.items() if p['loaded']], ['coding-128k'])
        self.current = 'other'
        second = {p['id']:p for p in json.loads(self.request('/models'))['data']}
        self.assertEqual([k for k,p in second.items() if p['loaded']], ['other'])
        self.assertEqual(json.loads(self.request('/models/other')), second['other'])
        self.current = None
        self.assertFalse(any(p['loaded'] for p in json.loads(self.request('/models'))['data']))
        self.loader.assert_not_called()
        self.assertFalse(self.backend.requests)

    def test_rejects_unauthorized_unknown_and_inactive_profiles(self):
        for path, body, key, status in [
            ('/models', None, 'wrong', 401),
            ('/chat/completions', {'model':'missing'}, 'fixture', 404),
            ('/responses', {'model':'other'}, 'fixture', 404),
        ]:
            with self.subTest(path=path), self.assertRaises(HTTPError) as exc:
                self.request(path, body, key)
            self.assertEqual(exc.exception.code,status)
        self.assertFalse(self.loads)
        self.assertFalse(self.backend.requests)

    def test_accepts_the_active_native_id_for_existing_clients(self):
        self.current = 'coding-128k'
        super().test_accepts_the_active_native_id_for_existing_clients()
        self.assertFalse(self.loads)

    def test_loads_requested_profiles_and_reuses_active_model(self):
        for key in ('coding-128k','coding-128k','coding-256k','other'):
            result=json.loads(self.request('/chat/completions',{'model':key,'messages':[]}))
            self.assertEqual(result['model'],key)
        self.assertEqual(self.loads,['coding-128k','coding-256k','other'])
        self.assertEqual([r[2]['model'] for r in self.backend.requests],['native','native','native','other'])

    def test_load_failure_and_cancelled_start_never_forward(self):
        for outcome in (RuntimeError('private runtime error'), {'cancelled':True}, {}):
            self.current=None
            self.loader.side_effect=outcome if isinstance(outcome,Exception) else None
            self.loader.return_value=outcome
            with self.subTest(outcome=outcome), self.assertRaises(HTTPError) as exc:
                self.request('/chat/completions',{'model':'other'})
            self.assertEqual(exc.exception.code,503)
            error=json.load(exc.exception)['error']
            self.assertEqual(error['code'],'model_load_failed')
            self.assertNotIn('private',error['message'])
        self.assertFalse(self.backend.requests)
        self.assertEqual(self.router.inflight,0)
        self.assertFalse(self.router.queue)

    def test_native_alias_loads_only_unambiguous_profile(self):
        with self.assertRaises(HTTPError) as exc:
            self.request('/chat/completions',{'model':'native'})
        self.assertEqual(exc.exception.code,400)
        self.assertFalse(self.loads)
        self.request('/chat/completions',{'model':'other'})
        self.assertEqual(self.loads,['other'])

    def test_listeners_share_router_and_wait_for_inflight_requests(self):
        second=self.start(make_server('fixture',lambda:self.profiles,self.router.active,
                                     port=0,backend_port=self.backend.server_port,router=self.router))
        self.current='coding-128k'
        with ThreadPoolExecutor(max_workers=2) as pool:
            with self.router.use('coding-128k',self.profiles):
                future=pool.submit(lambda: urlopen(Request(
                    f'http://127.0.0.1:{second.server_port}/v1/chat/completions',
                    data=b'{"model":"other"}',headers={'Authorization':'Bearer fixture'}),timeout=5).read())
                with self.router.condition:
                    self.assertTrue(self.router.condition.wait_for(lambda: bool(self.router.queue),timeout=2))
                # Another stream is still using the first profile.
                self.assertFalse(future.done())
                self.assertFalse(self.loads)
            self.assertEqual(json.loads(future.result(timeout=3))['model'],'other')
        self.assertEqual(self.loads,['other'])


class ProfileRouterTests(unittest.TestCase):
    def test_same_profile_requests_overlap_and_release_on_error(self):
        loader=Mock()
        router=ProfileRouter(lambda _: 'a',loader)
        with router.use('a',{}):
            with router.use('a',{}):
                self.assertEqual(router.inflight,2)
            try:
                with router.use('a',{}):raise OSError('client disconnected')
            except OSError:pass
            self.assertEqual(router.inflight,1)
        self.assertEqual(router.inflight,0)
        loader.assert_not_called()

    def test_wait_timeout_cleans_queue_and_allows_retry(self):
        router=ProfileRouter(lambda _: 'a',Mock(),timeout=.05)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with router.use('a',{}):
                def wait_other():
                    with router.use('b',{}):pass
                future=pool.submit(wait_other)
                with self.assertRaises(ProfileUnavailable) as exc:future.result(timeout=2)
                self.assertEqual(exc.exception.code,'model_wait_timeout')
                self.assertFalse(router.queue)
        with router.use('a',{}):self.assertEqual(router.inflight,1)
