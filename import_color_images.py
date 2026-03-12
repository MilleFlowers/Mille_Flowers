import sqlite3
import os
import mimetypes

def import_color_images():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()

    # Create table if not exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS produto_imagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_produto TEXT NOT NULL,
            cor TEXT NOT NULL,
            imagem_blob BLOB NOT NULL,
            imagem_mimetype TEXT NOT NULL,
            UNIQUE(nome_produto, cor)
        )
    """)
    conn.commit()

    # List static/img/ files
    img_dir = os.path.join("static", "img")
    
    if not os.path.exists(img_dir):
        print(f"Directory {img_dir} does not exist.")
        return

    files = [f for f in os.listdir(img_dir) if os.path.isfile(os.path.join(img_dir, f))]
    
    # We want to find files formatted like 'nome_cor.jpeg'
    # E.g., 'gerbera_azul_claro.jpeg'
    inserted_count = 0
    
    for filename in files:
        if filename.endswith(".jpeg") or filename.endswith(".png"):
            # Try to map filename to nome and cor based on products we know
            basename = os.path.splitext(filename)[0]
            
            # Known flower types that have colors
            flores = ["gerbera", "lotus", "lírio", "rosa", "tulipa", "caneta"]
            
            nome_flor = None
            cor_flor = None
            
            # Find which flower it is
            for flor in flores:
                if basename.startswith(flor + "_"):
                    nome_flor = flor.capitalize()
                    cor_flor = basename[len(flor)+1:]
                    break
            
            if nome_flor and cor_flor:
                # Read blob
                filepath = os.path.join(img_dir, filename)
                with open(filepath, "rb") as f:
                    blob = f.read()
                mimetype = mimetypes.guess_type(filename)[0] or "image/jpeg"
                
                try:
                    cursor.execute(
                        "INSERT INTO produto_imagens (nome_produto, cor, imagem_blob, imagem_mimetype) VALUES (?, ?, ?, ?)",
                        (nome_flor, cor_flor, blob, mimetype)
                    )
                    inserted_count += 1
                    print(f"Migrated: {nome_flor} - {cor_flor}")
                except sqlite3.IntegrityError:
                    print(f"Skipped (already exists): {nome_flor} - {cor_flor}")
    
    conn.commit()
    conn.close()
    
    print(f"Successfully migrated {inserted_count} color variation images to the DB.")

if __name__ == "__main__":
    import_color_images()
