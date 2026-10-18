"""Local installation paths. Copy config.example.json to config.json to override."""
import json,os,pathlib,shutil
ROOT=pathlib.Path(__file__).resolve().parent
CONFIG_PATH=pathlib.Path(os.environ.get('AI_PROFILES_CONFIG',str(ROOT/'config.json'))).resolve()
try:
 CONFIG=json.loads(CONFIG_PATH.read_text(encoding='utf-8-sig'))
 if not isinstance(CONFIG,dict):raise ValueError('configuration must be a JSON object')
except FileNotFoundError:CONFIG={}
def location(key,default):
 value=pathlib.Path(os.path.expandvars(str(CONFIG.get(key,default)))).expanduser()
 return (CONFIG_PATH.parent/value).resolve() if not value.is_absolute() else value.resolve()
WINDOWS_ROOT=pathlib.Path(os.environ.get('SystemRoot','C:/Windows'))
STRATA_ROOT=location('strata_root','C:/AI/Strata')
STRATA_PYTHON=location('strata_python',STRATA_ROOT/'Strata/.venv/Scripts/python.exe')
STATE_DIR=location('state_dir',pathlib.Path(os.environ.get('LOCALAPPDATA',str(pathlib.Path.home()/'AppData/Local')))/'AIProfiles')
NVIDIA_SMI=str(CONFIG.get('nvidia_smi') or shutil.which('nvidia-smi') or WINDOWS_ROOT/'System32/nvidia-smi.exe')
