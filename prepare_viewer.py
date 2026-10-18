"""Build calendar indexes and the separate readable-session atlas.

Run after an export. Safe to rerun; it prepares derivative indexes in
knowledge.sqlite and atlas.sqlite, never source databases or raw JSONL.
"""
import argparse
import sqlite3
from pathlib import Path


def build(root, progress=None):
    progress = progress or (lambda message: print(message, flush=True))
    dbfile = Path(root).resolve() / 'knowledge.sqlite'
    if not dbfile.is_file():
        raise FileNotFoundError(dbfile)
    db = sqlite3.connect(dbfile)
    try:
        db.execute('create index if not exists nodes_created on nodes(created, id)')
        db.execute('create index if not exists nodes_kind_created on nodes(kind, created, id)')
        db.execute('create table if not exists timeline_months (month text not null, kind text not null, records integer not null, primary key(month,kind))')
        db.execute('delete from timeline_months')
        db.execute("insert into timeline_months select substr(created,1,7),kind,count(*) from nodes where created glob '????-??-*' group by substr(created,1,7),kind")
        db.commit()
        progress('Timeline prepared: %d month/type groups' % db.execute('select count(*) from timeline_months').fetchone()[0])
    finally:
        db.close()
    from atlas import ensure
    progress('Preparing readable sessions and the visual atlas...')
    cache = ensure(root)
    progress('Session atlas prepared.')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output')
    build(p.parse_args().output)
