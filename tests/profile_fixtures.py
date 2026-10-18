"""Explicit isolated profiles for GUI/controller tests; never backend presets."""
import atexit
import json
import pathlib
import tempfile
from ai_profiles import ProfileStore,LEGACY_ALIASES

_directories=[]

def configure_launcher(module):
    directory=tempfile.TemporaryDirectory(prefix='valet-test-profiles-')
    _directories.append(directory);atexit.register(directory.cleanup)
    root=pathlib.Path(directory.name)
    store=ProfileStore(root/'backend',root/'state')
    for index,(key,stem) in enumerate(LEGACY_ALIASES.items()):
        path=store.paths(key)[0];path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(dict(exe='engine.exe',model_name='fixture-model',parallel=(1,1,2,3,4)[index],
            args=['--max-context',str((163840,262144,65536,163840,65536)[index])])),encoding='utf-8')
    module.CONFIG={**module.CONFIG,'enabled_profiles':list(LEGACY_ALIASES)}
    module.PROFILE_STORE=store
    module.reload_profiles()
    return store
