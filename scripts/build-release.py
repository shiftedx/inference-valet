"""Build a source-only release from a commit and reject unsafe or mismatched assets."""
import argparse
import hashlib
import pathlib
import re
import subprocess
import zipfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
BLOCKED_PARTS={'.git','.venv','__pycache__','AIProfiles','profile-logs','profile-backups',
               'integration-backups','launcher-logs','backups','.test-state','models','engine','engines','packs','.ssh'}
BLOCKED_NAMES={'config.json','.env','gui-session.json','idle-settings.json','ninfer-owner.json',
               'llamacpp-performance.json','.test-config.json'}
BLOCKED_SUFFIXES={'.gguf','.safetensors','.ninfer','.infernix','.bin','.exe','.dll','.jsonl',
                  '.log','.pid','.lock','.dmp','.pyc','.pyo','.pack','.onnx','.pt','.pth','.ckpt','.pem','.key','.p12','.pfx','.pdb','.lib','.obj','.o','.a'}
PRIVACY_PATTERNS={
    'personal path':re.compile(rb'[A-Za-z]:[\\/]+Users[\\/]+(?!Public\b|Default\b|Example\b|User\b|USERNAME\b)[^\\/\s\x22\x27]+',re.I),
    'private hostname':re.compile(rb'\b(?:[a-z0-9-]+\.)+local\b',re.I),
    'credential':re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{24,})\b'),
    'private key':re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----'),
}


def audit_archive(path,version):
    findings=[]
    prefix='inference-valet-'+version+'/'
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        for entry in archive.infolist():
            name=entry.filename
            relative=name.removeprefix(prefix)
            parts=pathlib.PurePosixPath(relative).parts
            if not name.startswith(prefix) or '..' in parts or relative.startswith('/'):
                findings.append((name,'invalid archive path'))
            if any(part in BLOCKED_PARTS for part in parts) or pathlib.PurePosixPath(relative).name in BLOCKED_NAMES or pathlib.PurePosixPath(relative).suffix.lower() in BLOCKED_SUFFIXES:
                findings.append((name,'private/runtime file'))
            if not entry.is_dir():
                data=archive.read(entry)
                for reason,pattern in PRIVACY_PATTERNS.items():
                    if pattern.search(data):findings.append((name,reason))
        if findings:
            # Report filenames/categories only, never matched credentials or values.
            raise ValueError('Release audit rejected: '+repr(findings))
        if archive.read(prefix+'VERSION').decode().strip()!=version:
            raise ValueError('Archive VERSION does not match the requested release')
        readme=archive.read(prefix+'README.md').decode()
        badge=archive.read(prefix+'docs/assets/version.svg').decode()
        if 'releases/tag/v'+version not in readme or 'Version '+version not in readme or 'version: '+version not in badge:
            raise ValueError('README/badge version does not match the release')
        for name in ('ai_capabilities.py','ai_provider.py','ai_dsv41.py','tests/test_capabilities.py'):
            if prefix+name not in names:raise ValueError('Release is missing '+name)
    return len(names)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version',required=True)
    parser.add_argument('--revision',default='HEAD')
    parser.add_argument('--output-dir',type=pathlib.Path,default=ROOT/'dist')
    args=parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+',args.version):parser.error('Use a numeric release version')
    commit=subprocess.check_output(['git','rev-parse',args.revision],cwd=ROOT,text=True).strip()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    path=args.output_dir/('inference-valet-'+args.version+'.zip')
    subprocess.run(['git','archive','--format=zip','--prefix=inference-valet-'+args.version+'/',
                    '-o',str(path.resolve()),commit],cwd=ROOT,check=True)
    try:count=audit_archive(path,args.version)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    (args.output_dir/'SHA256SUMS.txt').write_text(digest+'  '+path.name+'\n',encoding='ascii')
    print(f'{commit}: {count} entries; source archive passed audit; SHA256 {digest}')


if __name__=='__main__':main()
