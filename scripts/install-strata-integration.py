"""Install managed wrapper templates into an external, stopped Strata root."""
import argparse,json,pathlib,shutil,time,uuid
import psutil

SOURCE=pathlib.Path(__file__).resolve().parents[1]/'backends/strata'
WRAPPERS=('launch_strata_profile.py','managed_strata_server.py','stop_strata_profile.py')

def install(root,examples=False,replace=False):
    root=pathlib.Path(root).resolve()
    if not (root/'Strata/serve/server.py').is_file():
        raise ValueError('Install upstream Strata at <root>/Strata before installing the integration.')
    wrappers={root/name:(SOURCE/name).read_bytes() for name in WRAPPERS}
    changed=[path for path,raw in wrappers.items() if path.exists() and path.read_bytes()!=raw]
    if changed and not replace:
        raise ValueError('Existing wrappers differ. Stop Strata, then pass --replace-wrappers; existing files will be backed up.')
    if changed:
        for proc in psutil.process_iter(['exe','cmdline']):
            try:
                exe=pathlib.Path(proc.info['exe'] or '').resolve();args=proc.info['cmdline'] or []
                if exe in (root/'Strata/engine/strata.exe',root/'Strata/engine/strata-vision.exe') or (len(args)>1 and pathlib.Path(args[1]).resolve() in wrappers):
                    raise ValueError('A managed backend is running. Stop it before replacing provenance-checked wrappers.')
            except (psutil.NoSuchProcess,psutil.AccessDenied):continue
    originals={path:path.read_bytes() if path.exists() else None for path in wrappers}
    backup=None
    if changed:
        backup=root/'integration-backups'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);backup.mkdir(parents=True)
        for path in changed:(backup/path.name).write_bytes(originals[path])
    written=[]
    try:
        for path,raw in wrappers.items():
            if originals[path]==raw:continue
            temporary=path.with_suffix('.tmp')
            try:temporary.write_bytes(raw);temporary.replace(path);written.append(path)
            finally:temporary.unlink(missing_ok=True)
    except Exception:
        for path in reversed(written):
            if originals[path] is None:path.unlink(missing_ok=True)
            else:path.write_bytes(originals[path])
        raise
    created=[]
    if examples:
        directory=root/'profiles';directory.mkdir(exist_ok=True)
        for sample in sorted((SOURCE/'profiles').glob('*.example.json')):
            target=directory/sample.name.replace('.example.json','.json')
            if target.exists():continue
            content=sample.read_text(encoding='utf-8').replace('C:/AI/Strata-Valet',root.as_posix())
            # Exclusive creation protects existing calibrated profiles.
            with target.open('x',encoding='utf-8') as output:output.write(content)
            created.append(target)
    return dict(wrappers=len(wrappers),created_profiles=len(created),backup=None if backup is None else str(backup))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=pathlib.Path)
    parser.add_argument('--install-examples',action='store_true')
    parser.add_argument('--replace-wrappers',action='store_true')
    args=parser.parse_args()
    try:
        print(json.dumps(install(args.root,args.install_examples,args.replace_wrappers),indent=2))
        if args.install_examples:print('Correct placeholder model/runtime paths before loading. Existing profiles were preserved.')
    except (ValueError,OSError) as exc:parser.exit(1,str(exc)+'\n')

if __name__=='__main__':main()
