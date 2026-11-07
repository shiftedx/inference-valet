import gc
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
        self.api = self.start(make_server("fixture", lambda: self.profiles,
                                          lambda _: "coding-128k", port=0,
                                          backend_port=self.backend.server_port))

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
                                          port=0, backend_port=self.backend.server_port, router=self.router))

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
