import sqlite3

con = sqlite3.connect("data/app.db")
cur = con.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cur.fetchall()

print("Tables in DB:")
for t in tables:
    print("-", t[0])
