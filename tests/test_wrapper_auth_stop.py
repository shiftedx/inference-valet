"""Authenticated wrapper requests and fail-closed graceful shutdown."""
import contextlib,importlib.util,io,json,pathlib,tempfile,unittest
from unittest.mock import MagicMock,patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'backends/strata'/file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
launch=load('auth_wrapper','launch_strata_profile.py')
stop=load('stop_wrapper','stop_strata_profile.py')

class WrapperAuthTests(unittest.TestCase):
    def test_authenticated_get_and_post_preserve_origin_and_body(self):
        with patch.dict(launch.os.environ,{'STRATA_API_KEY':' fixture-key '}):
            def reply(request,timeout):
                self.assertEqual(request.get_header('Authorization'),'Bearer fixture-key')
                return io.BytesIO(b'{"loaded":true}')
            with patch.object(launch.urllib.request,'urlopen',side_effect=reply):
                self.assertTrue(launch.fetch('/v1/status','http://localhost:8080')['loaded'])
            request=launch.api_request('http://localhost:8080/unload',data=b'{}',headers={'Content-Type':'application/json','Origin':'http://localhost:8080'})
            self.assertEqual(request.get_method(),'POST');self.assertEqual(request.data,b'{}')
            self.assertEqual(request.get_header('Authorization'),'Bearer fixture-key')
            self.assertEqual(request.get_header('Origin'),'http://localhost:8080')
            self.assertEqual(request.get_header('Content-type'),'application/json')
    def test_keyless_loopback_remains_supported(self):
        with patch.dict(launch.os.environ,{},clear=True):
            self.assertIsNone(launch.api_request('http://localhost:8080/health').get_header('Authorization'))

class SafeStopTests(unittest.TestCase):
    def run_stop(self,mode):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);logs=root/'profile-logs';logs.mkdir()
            wrapper=root/'managed_strata_server.py'
            server=MagicMock(pid=12);server.create_time.return_value=2
            server.name.return_value='python.exe';server.cmdline.return_value=['python.exe',str(wrapper)]
            server.is_running.return_value=False
            native=MagicMock(pid=13);native.name.return_value='strata.exe'
            native.cmdline.side_effect=stop.psutil.AccessDenied(13)
            hidden=MagicMock(pid=14);hidden.name.return_value='python.exe'
            hidden.cmdline.side_effect=stop.psutil.AccessDenied(14)
            owner=MagicMock(pid=11);owner.children.return_value=[server,native,hidden];owner.is_running.return_value=False
            server.children.return_value=[native,hidden]
            state=dict(launcher_sha256='hash',server_sha256='hash',launcher_pid=11,launcher_started=1,
                       server_pid=12,server_started=2,stop_file='stop-fixture.request',token='fixture')
            if mode=='no-wrapper':server.cmdline.return_value=['python.exe',str(root/'unrelated.py')]
            if mode=='reused':server.create_time.return_value=3
            if mode=='unowned':owner.children.return_value=[]
            if mode=='provenance':state['launcher_sha256']='changed'
            if mode=='path':state['stop_file']='../stop-fixture.request'
            state_path=logs/'active-profile.json';state_path.write_text(json.dumps(state))
            with patch.object(stop,'root',root),patch.object(stop,'logs',logs),patch.object(stop,'state_path',state_path),patch.object(stop,'digest',return_value='hash'),patch.object(stop,'identity',return_value=owner),patch.object(stop.psutil,'Process',return_value=server),contextlib.redirect_stdout(io.StringIO()):
                if mode=='ok':self.assertEqual(stop.main(),0)
                else:
                    with self.assertRaises(RuntimeError):stop.main()
            self.assertEqual((logs/'stop-fixture.request').exists(),mode=='ok')
            native.cmdline.assert_not_called()
            for process in [owner,server,native,hidden]:
                process.terminate.assert_not_called();process.kill.assert_not_called()
    def test_native_access_denied_does_not_block_verified_stop(self):self.run_stop('ok')
    def test_unverified_shutdown_never_writes_stop_request(self):
        for mode in ['no-wrapper','reused','unowned','provenance','path']:
            with self.subTest(mode=mode):self.run_stop(mode)
    def test_launcher_identity_rejects_executable_script_and_pid_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory);script=root/'launch_strata_profile.py'
            for mode in ['ok','pid','exe','script']:
                process=MagicMock();process.create_time.return_value=2 if mode=='pid' else 1
                process.exe.return_value=str(root/('foreign.exe' if mode=='exe' else 'python.exe'))
                process.cmdline.return_value=['python.exe',str(root/'other.py' if mode=='script' else script)]
                process.cwd.return_value=str(root)
                current=MagicMock();current.exe.return_value=str(root/'python.exe')
                with self.subTest(mode=mode),patch.object(stop,'root',root),patch.object(stop.psutil,'Process',side_effect=[process,current]):
                    if mode=='ok':self.assertIs(stop.identity(11,1,script),process)
                    else:
                        with self.assertRaises(RuntimeError):stop.identity(11,1,script)
if __name__=='__main__':unittest.main()
