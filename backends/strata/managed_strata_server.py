"""Local-only stop request invokes Strata's existing graceful Ctrl+C shutdown path."""
import _thread,json,os,pathlib,sys,threading,time
root=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(root/'Strata'))
stop=pathlib.Path(os.environ['STRATA_LOCAL_STOP_FILE']);token=os.environ['STRATA_LOCAL_STOP_TOKEN']
def watch():
    while True:
        try:
            request=json.loads(stop.read_text())
            if request.get('token')==token:
                _thread.interrupt_main();return
        except (OSError,ValueError):pass
        time.sleep(.25)
threading.Thread(target=watch,daemon=True).start()
from serve import server
valet=os.environ.get('STRATA_VALET_ROOT')
if valet:
    sys.path.insert(0,valet)
    from ai_demand import install
    guard=install(server)
    # Every native retry checks the game guard before it can spawn GPU processes.
    for cls in (server.StrataEngine,server.Vision):
        original=cls.__init__
        def guarded(self,*args,_original=original,**kwargs):
            if not kwargs.get('lazy',False):
                if reason:=guard.admission():raise server.GpuBusy(reason,retry_after=15)
            return _original(self,*args,**kwargs)
        cls.__init__=guarded
sys.exit(server.main())
