"""Exercise installer boundaries in staged checkouts, never real shell/task locations."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
POWERSHELL=shutil.which('powershell.exe')

@unittest.skipUnless(os.name=='nt' and POWERSHELL,'Windows PowerShell required')
class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='valet lifecycle ')
        self.addCleanup(self.temp.cleanup)
        self.root=pathlib.Path(self.temp.name)/'checkout with spaces'
        self.root.mkdir();shutil.copytree(ROOT/'scripts',self.root/'scripts')
        self.links=self.root.parent/'sandbox shortcuts';self.links.mkdir()

    def ps(self,code,success=True):
        result=subprocess.run([POWERSHELL,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-Command',
                               "$ErrorActionPreference='Stop'; "+code],capture_output=True,text=True,timeout=120)
        if success:self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        else:self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
        return result

    @staticmethod
    def quote(value):return "'"+str(value).replace("'","''")+"'"

    def test_setup_clean_and_upgrade_preserve_config_and_state_without_shortcuts(self):
        (self.root/'requirements.txt').write_text('')
        config=self.root/'config.json';example=self.root/'config.example.json'
        example.write_text('{"first":true}')
        command=f'& {self.quote(self.root/"scripts/setup.ps1")} -Python {self.quote(sys.executable)} -NoShortcuts'
        self.ps(command);self.assertEqual(config.read_bytes(),example.read_bytes())
        original=b'{"custom":"preserve exact bytes"}\r\n';config.write_bytes(original)
        state=self.root/'state';state.mkdir();(state/'idle-settings.json').write_text('keep')
        external=self.root.parent/'external profiles';external.mkdir();(external/'calibrated.json').write_text('keep')
        self.ps(command)
        self.assertEqual(config.read_bytes(),original)
        self.assertEqual((state/'idle-settings.json').read_text(),'keep')
        self.assertEqual((external/'calibrated.json').read_text(),'keep')
        self.assertEqual(list(self.links.iterdir()),[])

    def test_task_removal_owned_foreign_missing_and_error(self):
        script=self.quote(self.root/'scripts/remove-startup.ps1');root=self.quote(self.root)
        owned=fr'''$root={root};$global:removed=0
function Get-ScheduledTask {{ [pscustomobject]@{{TaskName='AI Profiles - Idle Reload';TaskPath='\';Actions=@([pscustomobject]@{{Execute=(Join-Path $root '.venv\Scripts\pythonw.exe');Arguments=('"'+(Join-Path $root 'ai-launcher.py')+'" --tray');WorkingDirectory=$root}})}} }}
function Unregister-ScheduledTask {{param($TaskName,$TaskPath,$Confirm);$global:removed++}}
& {script};if($global:removed -ne 1){{throw 'Owned task not removed'}}'''
        self.ps(owned)
        self.ps(owned.replace("WorkingDirectory=$root",r"WorkingDirectory='C:\foreign'").replace('-ne 1','-ne 0'))
        self.ps(f'function Get-ScheduledTask {{}}; function Unregister-ScheduledTask {{throw "unexpected removal"}}; & {script}; & {script}')
        self.ps(f'function Get-ScheduledTask {{throw "provider denied"}}; & {script}',success=False)

    def test_uninstall_owned_links_only_preserves_data_and_is_idempotent(self):
        config=self.root/'config.json';config.write_bytes(b'{"keep":"settings"}\r\n')
        external=self.root.parent/'external-strata';external.mkdir();model=external/'model.gguf';model.write_bytes(b'preserve external model')
        self.ps(fr'''$shell=New-Object -ComObject WScript.Shell
$root={self.quote(self.root)};$path={self.quote(self.links/'Inference Valet.lnk')}
$link=$shell.CreateShortcut($path);$link.TargetPath=Join-Path $root '.venv\Scripts\pythonw.exe';$link.Arguments='"'+(Join-Path $root 'ai-launcher.py')+'"';$link.WorkingDirectory=$root;$link.Save()
& {self.quote(self.root/'scripts/uninstall.ps1')} -NoStartup -ShortcutDirectories {self.quote(self.links)}
if(Test-Path -LiteralPath $path){{throw 'Owned link remains'}}
& {self.quote(self.root/'scripts/uninstall.ps1')} -NoStartup -ShortcutDirectories {self.quote(self.links)}
$link=$shell.CreateShortcut($path);$link.TargetPath='C:\foreign\pythonw.exe';$link.Save()
& {self.quote(self.root/'scripts/uninstall.ps1')} -NoStartup -ShortcutDirectories {self.quote(self.links)}
if(-not(Test-Path -LiteralPath $path)){{throw 'Foreign link removed'}}''')
        self.assertTrue((self.root/'scripts/uninstall.ps1').exists())
        self.assertEqual(config.read_bytes(),b'{"keep":"settings"}\r\n')
        self.assertEqual(model.read_bytes(),b'preserve external model')

    def test_foreign_startup_install_refused_before_registration(self):
        result=self.ps(fr'''function Get-ScheduledTask {{ [pscustomobject]@{{TaskName='AI Profiles - Idle Reload';TaskPath='\';Actions=@([pscustomobject]@{{Execute='C:\foreign\pythonw.exe';Arguments='';WorkingDirectory='C:\foreign'}})}} }}
function Register-ScheduledTask {{throw 'Unexpected registration'}}
& {self.quote(self.root/'scripts/install-startup.ps1')}''',success=False)
        self.assertIn('belongs to another checkout',result.stderr)

    def test_foreign_shortcut_install_refuses_before_any_replacement(self):
        pythonw=self.root/'.venv/Scripts/pythonw.exe';pythonw.parent.mkdir(parents=True);pythonw.touch()
        icon=self.root/'docs/assets/inference-valet.ico';icon.parent.mkdir(parents=True);icon.touch()
        path=self.links/'Inference Valet.lnk'
        self.ps(fr'''$shell=New-Object -ComObject WScript.Shell;$link=$shell.CreateShortcut({self.quote(path)});$link.TargetPath='C:\foreign\pythonw.exe';$link.Save()''')
        original=path.read_bytes()
        result=self.ps(f'& {self.quote(self.root/"scripts/install-shortcuts.ps1")} -ShortcutDirectories {self.quote(self.links)}',success=False)
        self.assertIn('belongs to another checkout',result.stderr)
        self.assertEqual(path.read_bytes(),original)

if __name__=='__main__':unittest.main()
