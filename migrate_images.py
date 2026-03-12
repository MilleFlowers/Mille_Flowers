import sqlite3
import os
import mimetypes

def migrate_images():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    produtos = cursor.execute("SELECT id, imagem FROM produtos WHERE imagem_blob IS NULL").fetchall()
    
    print(f"Encontrados {len(produtos)} produtos sem BLOB.")
    
    for p in produtos:
        img_name = p["imagem"]
        img_path = os.path.join("static", "img", img_name)
        
        if os.path.exists(img_path):
            print(f"Migrando {img_name}...")
            with open(img_path, "rb") as f:
                blob = f.read()
            mimetype = mimetypes.guess_type(img_path)[0]
            
            cursor.execute(
                "UPDATE produtos SET imagem_blob = ?, imagem_mimetype = ? WHERE id = ?",
                (blob, mimetype, p["id"])
            )
        else:
            print(f"Aviso: Ficheiro {img_path} não encontrado.")
            
    conn.commit()
    conn.close()
    print("Migração concluída.")

if __name__ == "__main__":
    migrate_images()
