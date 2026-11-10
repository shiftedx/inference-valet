"""Runtime adapter for the local provider, using the desktop's profile ownership rules."""
import contextlib
import pathlib
import threading
import time
from collections import deque

import psutil

from ai_profiles import read_object


def positive_int(value):
    return value if type(value) is int and value > 0 else None


def option(args, flag):
    """Read a single explicit CLI override, including --flag=value."""
    values = []
    for index, arg in enumerate(args):
        if arg == flag:
            values.append(args[index + 1] if index + 1 < len(args) else None)
        elif arg.startswith(flag + "="):
            values.append(arg.partition("=")[2])
    if len(values) != 1:
        return None
    try:
        return positive_int(int(values[0]))
    except (TypeError, ValueError):
        return None


def catalog(profiles, store):
    result = {}
    for key, profile in profiles.items():
        item = dict(profile)
        context = profile["context"]
        strata = profile["engine"] == "strata"
        reserve = 8 if strata else 0
        ceiling = max(0, context - reserve)
        item.update(kv_shared=not strata, kv_cache_tokens=None,
                    kv_cache_tokens_per_slot=context if strata else None,
                    default_max_output_tokens=None, max_output_tokens=ceiling,
                    output_tokens_share_context=True, context_reserved_tokens=reserve)
        item["supports_vision"] = False
        if strata:
            try:
                path, _, _ = store.paths(key)
                source = read_object(path)
                vision = source.get("vision")
                item["supports_vision"] = ("--vision" in source.get("args", [])
                    and isinstance(vision, dict) and all(vision.get(field) for field in ("exe", "mmproj", "model")))
            except (OSError, ValueError, TypeError):
                pass
            # Logical live-session KV capacity, not GPU residency or parked history.
            item["kv_cache_tokens"] = context * profile["slots"]
            try:
                path, shared, _ = store.paths(key)
                limit = read_object(shared, {}).get("max_tokens", read_object(path).get("max_tokens"))
                if positive_int(limit):
                    item["default_max_output_tokens"] = min(limit, ceiling)
            except (OSError, ValueError, TypeError):
                pass
        else:
            args = profile.get("args") or []
            item["supports_vision"] = "--vision" in args
            item["kv_cache_tokens"] = option(args, "--kv-capacity")
            limit = option(args, "--default-max-tokens")
            if limit:
                item["default_max_output_tokens"] = min(limit, ceiling)
            if profile['engine'] == 'llamacpp':
                # Managed llama.cpp uses separate, fixed-size slot contexts.
                item.update(kv_shared=False, kv_cache_tokens=context * profile['slots'],
                            kv_cache_tokens_per_slot=context, supports_vision=False)
                limit = option(args, '--n-predict')
                item['default_max_output_tokens'] = min(limit, ceiling) if limit else None
        item["input_modalities"] = ["text", "image"] if item["supports_vision"] else ["text"]
        result[key] = item
    return result


def active_profile(profiles, processes, listener_for, native_owner, fetch, strata_root):
    try:
        listener = listener_for(processes())
        if listener is None:
            return None
        if (native := native_owner()) and native[0] == listener:
            key = native[1]["profile"]
            return key if key in profiles and profiles[key]["engine"] != "strata" else None
        status = fetch("/v1/status")
        if not listener.is_running() or listener_for([(listener, "strata-server")]) is None:
            return None
        matches = {key: profile for key, profile in profiles.items() if
                   profile["engine"] == "strata" and profile["model"] == status["model"] and
                   profile["context"] == status["context"]["native"] and
                   profile["slots"] == status["concurrency"]["serving"]}
        try:
            state = read_object(strata_root / "profile-logs/active-profile.json")
            if listener.pid == state["server_pid"] and abs(listener.create_time() - state["server_started"]) < .01:
                return next((key for key, profile in matches.items() if profile["profile"] == state["profile"]), None)
        except (OSError, ValueError, KeyError, TypeError):
            pass
        # A separate Strata launcher may have overwritten the snapshot. The listener
        # and its live model, context and slots still identify an unambiguous profile.
        return next(iter(matches)) if len(matches) == 1 else None
    except (OSError, ValueError, KeyError, TypeError, psutil.Error):
        return None


def loaded_profile(profiles, processes, listener_for, native_owner, fetch, strata_root):
    """Report resident weights only after rechecking the owned listener and launch."""
    try:
        key = active_profile(profiles, processes, listener_for, native_owner, fetch, strata_root)
        if key is None:
            return None
        profile = profiles[key]
        listener = listener_for(processes())
        if listener is None:
            return None
        if profile["engine"] != "strata":
            native = native_owner()
            if not native or native[0] != listener:
                return None
            if (pathlib.Path(profile["artifact"]).resolve() != pathlib.Path(native[1]["artifact"]).resolve()
                    or pathlib.Path(profile["exe"]).resolve() != pathlib.Path(native[1]["exe"]).resolve()):
                return None
            command = listener.cmdline()
            if profile['engine'] == 'llamacpp':
                from ai_llamacpp import matching_command, ready
                if not matching_command(command, profile) or not ready(profile, fetch):
                    return None
                engine = dict(max_context=profile['context'], max_concurrency=profile['slots'])
                matching_schema = True
            else:
                tail = command[command.index("--model-id") + 2:]
                if len(tail) >= 2 and tail[-2] == "--config":
                    tail = tail[:-2]  # Auth-only file created by the native wrapper.
                if tail != profile.get("args", []):
                    return None
            if profile["engine"] == "ninfer":
                stats = fetch("/stats")
                engine = stats.get("capacity") or {}
                models = fetch("/v1/models")
                matching_model = any(row.get("id") == profile["model"] for row in models.get("data", []))
                matching_schema = stats.get("object") == "ninfer.stats" and matching_model
            elif profile['engine'] != 'llamacpp':
                metrics = fetch("/metrics?format=json")
                engine = metrics.get("engine") or {}
                matching_schema = (metrics.get("schema") == "infernix.telemetry/1"
                                   and engine.get("model") == profile["model"])
            if (not matching_schema
                    or engine.get("max_context") != profile["context"]
                    or engine.get("max_concurrency") != profile["slots"]
                    or fetch("/health").get("status") != "ok"):
                return None
        else:
            status = fetch("/v1/status")
            if (status.get("loaded") is not True or status.get("model") != profile["model"]
                    or status.get("context", {}).get("native") != profile["context"]
                    or status.get("concurrency", {}).get("serving") != profile["slots"]):
                return None
        if not listener.is_running() or listener_for([(listener, "strata-server")]) != listener:
            return None
        return key
    except (OSError, ValueError, KeyError, TypeError, AttributeError, psutil.Error):
        return None


class ProfileUnavailable(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ProfileRouter:
    """Share a loaded profile across requests; drain streams before switching."""
    def __init__(self, active, load=None, timeout=620):
        self.active = active
        self.load = load
        self.timeout = timeout
        self.condition = threading.Condition()
        self.queue = deque()
        self.inflight = 0
        self.profile = None

    @contextlib.contextmanager
    def use(self, key, profiles):
        ticket = object()
        deadline = time.monotonic() + self.timeout
        with self.condition:
            self.queue.append(ticket)
            self.condition.notify_all()
            try:
                while self.queue[0] is not ticket or (self.inflight and self.profile != key):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ProfileUnavailable('model_wait_timeout', 'Timed out waiting for the requested model.')
                    self.condition.wait(remaining)
                if self.active(profiles) != key:
                    if self.inflight:
                        raise ProfileUnavailable('backend_changed', 'The backend changed during active requests. Retry when they finish.')
                    if self.load is None:
                        raise ProfileUnavailable('profile_inactive', 'Load this profile in Valet, then retry.')
                    try:
                        result = self.load(key)
                    except Exception as exc:
                        raise ProfileUnavailable('model_load_failed', 'Could not load the requested model. Check Valet diagnostics.') from exc
                    if (result or {}).get('cancelled') or self.active(profiles) != key:
                        raise ProfileUnavailable('model_load_failed', 'The requested model did not become ready.')
                self.profile = key
                self.inflight += 1
            finally:
                self.queue.remove(ticket)
                self.condition.notify_all()
        try:
            yield
        finally:
            with self.condition:
                self.inflight -= 1
                self.condition.notify_all()
