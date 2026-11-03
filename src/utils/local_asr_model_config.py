"""Explicit, read-only four-model path binding; no ModelScope calls or downloads."""
import hashlib
import json
from pathlib import Path

ROLES=('asr','vad','punc','spk')
WEIGHT_NAMES={'asr':'model.pt','vad':'model.pt','punc':'model.pt','spk':'campplus_cn_common.bin'}


def file_sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def resolve_verified_models(config_path):
    config=json.loads(Path(config_path).read_text(encoding='utf-8-sig'))
    if config.get('schema')!='verified_local_asr_paths_v1' or config.get('remote_download_allowed') is not False:
        raise ValueError('INVALID_LOCAL_ASR_CONFIG')
    rows=config.get('models',[])
    if len(rows)!=4 or sorted(x.get('role','') for x in rows)!=sorted(ROLES):
        raise ValueError('FOUR_UNIQUE_ASR_ROLES_REQUIRED')
    paths={}
    for row in rows:
        root=Path(row['directory'])
        if not root.is_absolute() or not root.is_dir():raise ValueError('LOCAL_ASR_DIRECTORY_MISSING')
        files=row.get('files',[])
        names=[x.get('name') for x in files]
        if len(names)!=len(set(names)) or not {WEIGHT_NAMES[row['role']],'config.yaml','configuration.json'}<=set(names):
            raise ValueError('LOCAL_ASR_REQUIRED_FILES_NOT_FROZEN')
        for record in files:
            name=record['name']
            if Path(name).name!=name:raise ValueError('LOCAL_ASR_FILE_OUTSIDE_DIRECTORY')
            p=root/name
            if not p.is_file() or not p.resolve().is_relative_to(root.resolve()):raise ValueError('LOCAL_ASR_FILE_MISSING_OR_ESCAPED')
            if p.stat().st_size!=record['bytes'] or file_sha256(p)!=record['sha256']:
                raise ValueError('LOCAL_ASR_FILE_IDENTITY_MISMATCH')
        paths[row['role']]=str(root.resolve())
    return tuple(paths[role] for role in ROLES)
