#!/usr/bin/env python3
"""Inventory and preserve non-document Pieces data without running Pieces."""
import argparse,hashlib,json,os,shutil,sqlite3
from pathlib import Path

CATEGORIES=('vector_db','couchbase.cblite2/Attachments','Formats')

def pieces_dir(source):
    p=Path(source).expanduser().resolve()
    for q in (p,p/'Pieces',p/'Pieces OS/com.pieces.os/production/Pieces',p/'com.pieces.os/production/Pieces'):
        if (q/'couchbase.cblite2/db.sqlite3').is_file():return q
    raise FileNotFoundError('No Pieces/couchbase.cblite2/db.sqlite3 found in '+str(p))

def inventory(source):
    root=pieces_dir(source);out={'source':str(root),'categories':{},'client_caches':[]}
    for cat in CATEGORIES:
        folder=root/cat;count=size=0;files=[]
        if folder.exists():
            for base,dirs,names in os.walk(folder):
                dirs[:]=[d for d in dirs if not (Path(base)/d).is_symlink()]
                for name in names:
                    p=Path(base)/name
                    if p.is_symlink():continue
                    try:n=p.stat().st_size
                    except OSError:continue
                    count+=1;size+=n;files.append({'path':str(p.relative_to(root)),'bytes':n})
        out['categories'][cat]={'count':count,'bytes':size,'files':files}
    for parent in (root.parents[2]/'production',root.parents[3]/'Pieces for Developers/com.pieces.pfd/production'):
        p=parent/'pieces_client_sqlite.db'
        if p.is_file():out['client_caches'].append({'path':str(p),'bytes':p.stat().st_size})
    return out

def archive(source,output):
    root=pieces_dir(source);out=Path(output).expanduser().resolve()
    if out.exists() and any(out.iterdir()):raise FileExistsError('Choose an empty archive directory')
    out.mkdir(parents=True,exist_ok=True,mode=0o700)
    ledger={'source':str(root),'files':[]}
    for cat in CATEGORIES:
        folder=root/cat
        if not folder.exists():continue
        for base,dirs,names in os.walk(folder):
            dirs[:]=[d for d in dirs if not (Path(base)/d).is_symlink()]
            for name in names:
                p=Path(base)/name
                if p.is_symlink() or not p.is_file() or name.endswith(('-lock','.lock','.lock_info','-shm')):continue
                rel=p.relative_to(root);dest=out/rel;dest.parent.mkdir(parents=True,exist_ok=True)
                digest=hashlib.sha256()
                with p.open('rb') as inp,dest.open('wb') as target:
                    for block in iter(lambda:inp.read(4*1024*1024),b''):
                        target.write(block);digest.update(block)
                ledger['files'].append({'path':str(rel),'bytes':dest.stat().st_size,'sha256':digest.hexdigest()})
    (out/'manifest.json').write_text(json.dumps(ledger,indent=2),encoding='utf-8')
    print('Archived',len(ledger['files']),'files in',out)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest='cmd',required=True)
    a=s.add_parser('inventory');a.add_argument('source');a=s.add_parser('archive');a.add_argument('source');a.add_argument('output')
    args=p.parse_args()
    if args.cmd=='inventory':
        data=inventory(args.source)
        print(json.dumps({'source':data['source'],'categories':{k:{'count':v['count'],'bytes':v['bytes']} for k,v in data['categories'].items()},'client_caches':data['client_caches']},indent=2))
    else:archive(args.source,args.output)
