"""OpenAI-compatible discovery and inference for Valet's configured profiles."""
import hmac
import ipaddress
import http.client
import json
import time
import uuid
from ai_issues import record_issue
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

from ai_provider_runtime import ProfileRouter, ProfileUnavailable

PORT = 8079
BACKEND_PORT = 8080
CHAT = "/v1/chat/completions"
RESPONSES = "/v1/responses"
MAX_BODY = 64 * 1024 * 1024


def model_info(key, profile, loaded=False):
    context = profile["context"]
    result = dict(id=key, object="model", created=0, owned_by="inference-valet",
                  name=profile["label"], context_length=context,
                  backend=profile["engine"], backend_model=profile["model"],
                  parallel_slots=profile["slots"], loaded=bool(loaded))
    for field in ("kv_cache_tokens", "kv_shared", "kv_cache_tokens_per_slot",
                  "default_max_output_tokens", "max_output_tokens",
                  "output_tokens_share_context", "context_reserved_tokens",
                  "supports_vision", "input_modalities"):
        if field in profile:
            result[field] = profile[field]
    return result


def alias_response(payload, profile_id):
    if isinstance(payload, dict):
        if "model" in payload:
            payload["model"] = profile_id
        response = payload.get("response")
        if isinstance(response, dict) and "model" in response:
            response["model"] = profile_id
    return payload


def make_server(key, profiles, active_profile, port=PORT, backend_port=BACKEND_PORT, lan=None, lan_clients=None, router=None, loaded_profile=None, diagnostics=record_issue):
    """Bind loopback or a specific LAN address and restrict LAN peers to its subnet."""
    if not key:
        raise ValueError("Set the Valet API token before starting the provider endpoint.")
    interface = ipaddress.IPv4Interface(lan) if lan else None
    if interface and (interface.ip.is_loopback or interface.ip.is_unspecified or
                      interface.ip.is_multicast or interface.network.prefixlen < 8):
        raise ValueError("Set provider_lan to a specific IPv4 address and LAN subnet.")
    allowed = ()
    if interface:
        if lan_clients is not None and (not isinstance(lan_clients, list) or not lan_clients):
            raise ValueError("Set provider_lan_clients to a list of allowed IPv4 subnets.")
        allowed = tuple(ipaddress.IPv4Network(value) for value in lan_clients) if lan_clients else (interface.network,)
    router = router or ProfileRouter(active_profile)
    resident_profile = loaded_profile or active_profile
    bearer = "Bearer " + key
    authorization = bearer.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def send_json(self, status, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if request_id := getattr(self, "request_id", None):
                self.send_header("X-Request-ID", request_id)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def error(self, status, message, code, param=None):
            kind = {401: "authentication_error", 502: "server_error", 503: "server_error"}.get(
                status, "invalid_request_error")
            self.send_json(status, {"error": dict(message=message, type=kind, code=code, param=param)})

        def authorized(self):
            if interface and not any(ipaddress.IPv4Address(self.client_address[0]) in subnet for subnet in allowed):
                self.error(403, "This provider is restricted to the configured LAN subnets.", "access_denied")
                return False
            value = self.headers.get("Authorization", "").encode("utf-8")
            if hmac.compare_digest(value, authorization):
                return True
            self.error(401, "A valid Valet API token is required.", "invalid_api_key")
            return False

        def do_GET(self):
            if not self.authorized():
                return
            path = urlsplit(self.path).path.rstrip("/")
            catalog = profiles()
            if path == "/v1/models":
                loaded = resident_profile(catalog)
                self.send_json(200, dict(object="list", data=[
                    model_info(k, p, loaded=k == loaded) for k, p in catalog.items()]))
                return
            if path.startswith("/v1/models/"):
                key = unquote(path.removeprefix("/v1/models/"))
                if key in catalog:
                    self.send_json(200, model_info(key, catalog[key], loaded=key == resident_profile(catalog)))
                    return
                self.error(404, "Unknown Valet profile.", "model_not_found", "model")
                return
            self.error(404, "Unknown provider endpoint.", "not_found")

        def reject_body(self, reason, status=400, exception_type=None):
            # Counts and fixed reason codes only: never log bodies, header values or exception text.
            details = dict(request_id=self.request_id, endpoint=urlsplit(self.path).path,
                           reason=reason, status=status, body_bytes_declared=self.body_declared,
                           body_bytes_received=self.body_received,
                           elapsed_seconds=round(time.monotonic() - self.body_started, 3))
            if exception_type:
                details["exception_type"] = exception_type
            try:
                diagnostics("provider_request_rejected", "Valet rejected an inference request before routing.", **details)
            except Exception:
                pass  # Diagnostics must not prevent the HTTP response.
            if status == 413:
                self.error(413, "Request body is too large.", "request_too_large")
            else:
                self.error(400, "Send a JSON object with a model profile ID.", "invalid_request", "model")

        def do_POST(self):
            if not self.authorized():
                return
            path = urlsplit(self.path).path.rstrip("/")
            if path not in (CHAT, RESPONSES):
                self.error(404, "Unknown provider endpoint.", "not_found")
                return
            self.request_id = uuid.uuid4().hex
            self.body_declared = None
            self.body_received = 0
            self.body_started = time.monotonic()
            if self.headers.get("Transfer-Encoding"):
                self.reject_body("unsupported_transfer_encoding")
                return
            lengths = self.headers.get_all("Content-Length", [])
            if not lengths:
                self.reject_body("missing_content_length")
                return
            try:
                if len(lengths) != 1:
                    raise ValueError
                size = int(lengths[0])
                if size < 1:
                    raise ValueError
                self.body_declared = size
            except ValueError:
                self.reject_body("invalid_content_length")
                return
            if size > MAX_BODY:
                self.reject_body("body_too_large", status=413)
                return
            body = bytearray()
            try:
                while self.body_received < size:
                    chunk = self.rfile.read1(min(65536, size - self.body_received))
                    if not chunk:
                        self.reject_body("incomplete_body")
                        return
                    body.extend(chunk)
                    self.body_received += len(chunk)
            except TimeoutError:
                self.reject_body("body_read_timeout", exception_type="TimeoutError")
                return
            except OSError:
                self.reject_body("body_read_error", exception_type="OSError")
                return
            try:
                payload = json.loads(body)
            except UnicodeDecodeError:
                self.reject_body("invalid_utf8")
                return
            except ValueError:
                self.reject_body("invalid_json")
                return
            if not isinstance(payload, dict):
                self.reject_body("not_json_object")
                return
            key = payload.get("model")
            if not isinstance(key, str) or not key:
                self.reject_body("invalid_model_field")
                return
            catalog = profiles()
            active = active_profile(catalog)
            profile_key = key
            if key not in catalog:
                matches = [k for k, p in catalog.items() if p["model"] == key]
                if active in matches:
                    profile_key = active
                elif len(matches) == 1:
                    profile_key = matches[0]
                elif matches:
                    self.error(400, "This backend model has multiple profiles. Use a Valet profile ID.", "ambiguous_model", "model")
                    return
            profile = catalog.get(profile_key)
            if profile is None:
                self.error(404, "Unknown Valet profile.", "model_not_found", "model")
                return
            if path == RESPONSES and profile["engine"] != "strata":
                self.error(404, "Use Chat Completions with this backend.", "unsupported_endpoint")
                return
            try:
                with router.use(profile_key, catalog):
                    payload["model"] = profile["model"]
                    self.forward(path, payload, key)
            except ProfileUnavailable as exc:
                self.error(503, str(exc), exc.code, "model")

        def forward(self, path, payload, key):
            conn = http.client.HTTPConnection("127.0.0.1", backend_port, timeout=620)
            started = False
            try:
                conn.request("POST", path, body=json.dumps(payload).encode("utf-8"),
                             headers={"Content-Type": "application/json",
                                      "Authorization": bearer})
                response = conn.getresponse()
                content_type = response.getheader("Content-Type", "application/json")
                if content_type.startswith("text/event-stream"):
                    started = True
                    self.send_response(response.status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    for line in response:
                        if line.startswith(b"data:") and line.strip() != b"data: [DONE]":
                            try:
                                event = alias_response(json.loads(line[5:]), key)
                                line = b"data: " + json.dumps(event).encode("utf-8") + b"\n"
                            except ValueError:
                                pass
                        self.wfile.write(line)
                        self.wfile.flush()
                    return
                data = response.read()
                if content_type.startswith("application/json") and response.status < 400:
                    data = json.dumps(alias_response(json.loads(data), key)).encode("utf-8")
                started = True
                self.send_response(response.status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                if retry := response.getheader("Retry-After"):
                    self.send_header("Retry-After", retry)
                self.end_headers()
                self.wfile.write(data)
            except (OSError, http.client.HTTPException, ValueError):
                if not started:
                    self.error(502, "The Valet backend could not answer the request.", "backend_unavailable")
            finally:
                conn.close()

    return ThreadingHTTPServer((str(interface.ip) if interface else "127.0.0.1", port), Handler)
