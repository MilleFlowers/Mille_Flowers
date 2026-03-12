import sqlite3

def verify_images():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    produtos = cursor.execute("SELECT id, nome, imagem, imagem_blob IS NOT NULL as has_blob FROM produtos").fetchall()
    
    print(f"Total de produtos: {len(produtos)}")
    for p in produtos:
        status = "Tem BLOB" if p["has_blob"] else "SEM BLOB"
        print(f"[{p['id']}] {p['nome']} (Imagem: {p['imagem']}) -> {status}")
        
    conn.close()

if __name__ == "__main__":
    verify_images()
