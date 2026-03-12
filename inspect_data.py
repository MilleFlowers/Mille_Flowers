import sqlite3

conn = sqlite3.connect("database.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("--- PRODUTOS ---")
produtos = cursor.execute("SELECT id, nome, cor, imagem, imagem_url FROM produtos").fetchall()
for p in produtos:
    print(dict(p))

print("\n--- CORES ---")
cores = cursor.execute("SELECT * FROM cores").fetchall()
for c in cores:
    print(dict(c))

conn.close()
