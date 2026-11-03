"""Local NInfer-family profiles and memory-guarded native server ownership."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

import psutil

from ai_config import CONFIG, STATE_DIR
from ai_idle import GameDetector, Settings
from ai_issues import write_json
from ai_profiles import profile_name, safe_stem


ROOT = pathlib.Path(__file__).resolve().parent
OWNER = STATE_DIR / "ninfer-owner.json"


def descriptors(python):
    profiles = {}
    for key, entry in CONFIG.get("ninfer_profiles", {}).items():
        safe_stem(key)
        engine, model_file = (pathlib.Path(entry[name]) for name in ("exe", "artifact"))
        if not engine.is_absolute() or not model_file.is_absolute():
            raise ValueError("NInfer profiles require absolute executable and artifact paths")
        backend = entry.get("engine", "ninfer")
        if backend not in ("ninfer", "infernix") or engine.name.lower() != backend + "-serve.exe":
            raise ValueError("NInfer profiles require a matching native serve executable")
        if backend == "ninfer" and entry.get("auth"):
            raise ValueError("Valet token forwarding requires Infernix's TOML configuration support")
        context, slots = entry["context"], entry.get("slots", 1)
        if type(context) is not int or context < 1 or type(slots) is not int or slots < 1:
            raise ValueError("NInfer context and slots must be positive integers")
        args = entry.get("args", [])
        if not isinstance(args, list) or any(not isinstance(arg, str) or
                arg.partition("=")[0] in {"--host", "--port", "--max-context", "--max-concurrency", "--model-id", "--config"}
                for arg in args):
            raise ValueError("NInfer extra args must not override listener, context, or slots")
        label = profile_name(entry["label"], context, slots)
        if slots > 1:
            window = f"{context // 1024}K" if context % 1024 == 0 else f"{context:,}"
            label = f'{entry["label"]} · {slots} slots · {window} request limit'
        profiles[key] = dict(label=label, name=label, profile=key, engine=backend,
                             context=context, slots=slots, model=entry["model"],
                             exe=engine, artifact=model_file, args=args,
                             command=[str(python), str(__file__), key], cwd=str(ROOT))
    return profiles


def verify_assets(profile):
    for key in ("exe", "artifact"):
        if not profile[key].is_file():
            raise ValueError(f"Missing NInfer {key}: {profile[key]}")


def owned_process():
    try:
        record = json.loads(OWNER.read_text())
        process = psutil.Process(record["pid"])
        if abs(process.create_time() - record["created"]) > .01:
            return None
        if pathlib.Path(process.exe()).resolve() != pathlib.Path(record["exe"]).resolve():
            return None
        command = process.cmdline()
        if len(command) < 2 or pathlib.Path(command[1]).resolve() != pathlib.Path(record["artifact"]).resolve():
            return None
        return process, record
    except (OSError, ValueError, KeyError, psutil.Error):
        return None


def run(key):
    from ai_demand import Guard
    from ai_telemetry import host_hardware
    profile = descriptors(sys.executable)[key]
    launch_stamp = int(os.environ["VALET_NINFER_STARTED"])

    def cancelled():
        try:
            return int((STATE_DIR / "last-stop.txt").read_text()) > launch_stamp
        except FileNotFoundError:
            return False

    verify_assets(profile)
    if owned_process():
        raise RuntimeError("An owned NInfer server is already running")
    game_guard = Guard()
    if reason := game_guard.load_reason():
        raise RuntimeError(reason)
    if cancelled():
        return 0
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    command = [str(profile["exe"]), str(profile["artifact"]), "--host", "127.0.0.1", "--port", "8080",
               "--max-context", str(profile["context"]), "--max-concurrency", str(profile["slots"]),
               "--model-id", profile["model"], *profile["args"]]
    credential_file = None
    child = None
    record = None
    try:
        if CONFIG["ninfer_profiles"][key].get("auth"):
            secret = str(CONFIG.get("strata_api_key") or os.environ.get("STRATA_API_KEY") or "").strip()
            if not secret:
                raise ValueError("NInfer API authentication requires a Valet API token")
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".toml",
                                             prefix="ninfer-auth-", dir=STATE_DIR, delete=False) as settings:
                credential_file = pathlib.Path(settings.name)
                settings.write("api-key = " + json.dumps(secret) + "\n")
            command.extend(["--config", str(credential_file)])
        child = subprocess.Popen(command, cwd=profile["exe"].parent)
        process = psutil.Process(child.pid)
        record = dict(pid=child.pid, created=process.create_time(), profile=key,
                      exe=str(profile["exe"]), artifact=str(profile["artifact"]))
        write_json(OWNER, record)
        low_since = None
        next_game_check = 0
        while child.poll() is None:
            if cancelled():
                return 0
            hardware = host_hardware()
            commit = hardware.get("commit_free_gib")
            ram = hardware["ram_free_gib"]
            now = time.monotonic()
            if now >= next_game_check:
                game_guard.sample()
                next_game_check = now + game_guard.options["poll_seconds"]
                if game_guard.game_since is not None and now - game_guard.game_since >= game_guard.options["grace_seconds"]:
                    print("Gaming priority: unloading the NInfer model", flush=True)
                    return 0
            low = commit is None or commit < 2 or ram < 4
            low_since = (low_since if low_since is not None else now) if low else None
            if (commit is not None and commit < 1) or (low_since is not None and now - low_since >= 3):
                raise RuntimeError(f"MEMORY GUARD: NInfer stopped, free RAM {ram:.2f} GiB, commit headroom {commit}")
            time.sleep(.5)
        return child.returncode
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=15)
        try:
            if record and json.loads(OWNER.read_text()) == record:
                OWNER.unlink()
        except (OSError, ValueError):
            pass
        if credential_file:
            credential_file.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1]))
