"""Bounded reads of the configuration and log belonging to a verified server."""
import json
import pathlib
import psutil


def read_json(path, limit=256 * 1024):
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Runtime configuration exceeds the observation limit')
    result = json.loads(data.decode('utf-8-sig'))
    if not isinstance(result, dict):
        raise ValueError('Runtime configuration must be an object')
    return result


class RuntimeDetailsReader:
    def __init__(self, root):
        self.logs = (pathlib.Path(root) / 'profile-logs').resolve()
        self.key = None
        self.snapshot = (None, '')
        self.profile = None

    def _inside(self, value, suffix):
        path = pathlib.Path(value).resolve()
        if not path.is_relative_to(self.logs) or path.suffix.lower() != suffix:
            raise ValueError('Runtime file is outside the managed profile log directory')
        return path

    def read(self, processes, listener):
        try:
            active = read_json(self.logs / 'active-profile.json')
            server = next((p for p, kind in processes if kind == 'strata-server'
                           and p.pid == active.get('server_pid')
                           and abs(p.create_time() - active['server_started']) < .01), None)
            if server is None or not server.is_running():
                raise ValueError('No current managed server owns this runtime configuration')
            if listener is None or not listener.is_running():
                raise ValueError('No verified API listener')
            # Windows venv redirectors can leave a wrapper PID in the launcher
            # record. The actual listener must be that process or its child.
            if server.pid != listener.pid and not any(
                    p.pid == listener.pid and abs(p.create_time() - listener.create_time()) < .01
                    for p in server.children(recursive=True)):
                raise ValueError('Runtime record belongs to a different server')
            self.profile = active.get('profile')
            config_path = self._inside(active['config'], '.json')
            config_stat = config_path.stat()
            configuration = read_json(config_path)
            log_path = self._inside(configuration['log'], '.log')
            log_stat = log_path.stat()
            key = (server.pid, server.create_time(), str(config_path), config_stat.st_mtime_ns,
                   config_stat.st_size, str(log_path), log_stat.st_mtime_ns, log_stat.st_size)
            if key != self.key:
                with log_path.open('rb') as stream:
                    stream.seek(max(0, log_stat.st_size - 192 * 1024))
                    text = stream.read(192 * 1024).decode('utf-8', errors='replace')
                self.key, self.snapshot = key, (configuration, text)
            if not server.is_running() or not listener.is_running():
                raise ValueError('Runtime owner exited during observation')
            return self.snapshot
        except (OSError, ValueError, KeyError, TypeError, StopIteration, psutil.Error):
            self.key, self.snapshot = None, (None, '')
            self.profile = None
            return self.snapshot

    def pending_memory(self, configuration):
        """Compare saved memory options with this listener's launch snapshot."""
        from ai_profiles import argument
        profile = self.profile
        if not isinstance(profile, str) or not profile or any(
                not (c.isascii() and (c.isalnum() or c in '-_')) for c in profile):
            return None
        try:
            saved = read_json(self.logs.parent / 'profiles' / (profile + '.json'))
            from ai_next_load import ENGINE_FLAGS
            flags = ENGINE_FLAGS
            return any(argument(saved.get('args', []), flag) != argument(
                configuration.get('args', []), flag) for flag in flags)
        except (OSError, ValueError, KeyError, TypeError):
            return None
