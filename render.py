#!/usr/bin/env python3
"""Optional offline output formats from the canonical knowledge.sqlite index."""
import argparse,csv,html,json,re,sqlite3,xml.sax.saxutils as xml
from pathlib import Path

def render(root,formats,limit=0):
    root=Path(root).resolve();dbfile=root/'knowledge.sqlite'
    if not dbfile.exists():raise FileNotFoundError(dbfile)
    db=sqlite3.connect(dbfile.as_uri()+'?mode=ro',uri=True)
    selector='select id,kind,title,body,created,updated,json from nodes order by kind,id'+(' limit '+str(limit) if limit else '')
    out=root/'optional';out.mkdir(exist_ok=True)
    if 'markdown' in formats:
        md=out/'wiki';md.mkdir(exist_ok=True);n=0
        for id,kind,title,body,created,updated,document in db.execute(selector):
            folder=md/kind;folder.mkdir(exist_ok=True)
            # Stable UUID filename, no untrusted path components.
            if not re.fullmatch(r'[0-9a-fA-F-]{36}',id):continue
            refs=db.execute('select e.predicate,e.dst,n.kind from edges e join nodes n on n.id=e.dst where e.src=? order by e.predicate,e.dst limit 1000',(id,)).fetchall()
            links='\n'.join('- '+p+': [source](../'+target_kind+'/'+dst+'.md)' for p,dst,target_kind in refs if re.fullmatch(r'[0-9a-fA-F-]{36}',dst))
            text='# '+(title or kind).replace('\n',' ')+'\n\nID: `'+id+'`  \nType: `'+kind+'`  \nCreated: '+(created or '')+'\n\n'+(body or '')+'\n\n## Relationships\n'+links+'\n\n## Original JSON\n\n```json\n'+json.dumps(json.loads(document),ensure_ascii=False,indent=2)+'\n```\n'
            (folder/(id+'.md')).write_text(text,encoding='utf-8');n+=1
        print('Markdown:',n,'pages in',md)
    if 'neo4j' in formats:
        with (out/'neo4j-nodes.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['id:ID','kind','title','body','created','updated',':LABEL'])
            for id,kind,title,body,created,updated,_ in db.execute(selector):w.writerow([id,kind,title,(body or '')[:1000000],created,updated,'Memory'])
        with (out/'neo4j-edges.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f);w.writerow([':START_ID','predicate',':END_ID',':TYPE'])
            query='select e.src,e.predicate,e.dst from edges e join nodes a on a.id=e.src join nodes b on b.id=e.dst'
            if limit:query+=' limit '+str(limit)
            for src,p,dst in db.execute(query):w.writerow([src,p,dst,'RELATED_TO'])
        print('Neo4j CSV:',out)
    db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('export_dir');p.add_argument('--format',action='append',choices=('markdown','neo4j'),required=True);p.add_argument('--limit',type=int,default=0);a=p.parse_args();render(a.export_dir,a.format,a.limit)
