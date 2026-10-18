#!/usr/bin/env python3
"""Optional offline output formats from the canonical knowledge.sqlite index."""
import argparse,csv,sqlite3
from pathlib import Path

def render(root,formats,limit=0,output=None):
    root=Path(root).resolve();dbfile=root/'knowledge.sqlite'
    if not dbfile.exists():raise FileNotFoundError(dbfile)
    if limit < 0:raise ValueError('The test limit must be zero or positive.')
    if 'markdown' in formats:
        if limit:raise ValueError('Markdown requires the full saved export; --limit is only available for Neo4j.')
        if output is None:raise ValueError('Markdown requires --output NEW_NOTES_FOLDER outside the saved archive.')
        from portable import export_markdown
        export_markdown(root,output,progress=print)
    if 'neo4j' not in formats:return
    db=sqlite3.connect(dbfile.as_uri()+'?mode=ro',uri=True)
    selector='select id,kind,title,body,created,updated,json from nodes order by kind,id'+(' limit '+str(limit) if limit else '')
    out=root/'optional';out.mkdir(exist_ok=True)
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
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('export_dir');p.add_argument('--format',action='append',choices=('markdown','neo4j'),required=True);p.add_argument('--limit',type=int,default=0);p.add_argument('--output',help='New external destination for Markdown');a=p.parse_args();render(a.export_dir,a.format,a.limit,a.output)
