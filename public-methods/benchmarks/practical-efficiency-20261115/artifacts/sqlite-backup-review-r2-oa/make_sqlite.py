"""Optional public synthetic fixture, unrelated to hidden row values."""
import sqlite3,sys
from pathlib import Path
def make(path):
    path=Path(path)
    if path.exists():raise FileExistsError(path)
    c=sqlite3.connect(path)
    c.executescript('CREATE TABLE desks(id INTEGER PRIMARY KEY,label TEXT); CREATE TABLE tickets(id INTEGER PRIMARY KEY,desk_id INTEGER REFERENCES desks(id)); INSERT INTO desks VALUES(1,"north"); INSERT INTO tickets VALUES(5,1),(6,404);')
    c.commit();c.close()
if __name__=='__main__':make(sys.argv[1])
