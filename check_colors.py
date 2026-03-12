import sqlite3

def check_colors():
    conn = sqlite3.connect("database.db")
    
    # Let's see what is in produto_imagens
    images = conn.execute("SELECT nome_produto, cor FROM produto_imagens").fetchall()
    print("--- Imagens cadastradas no banco de dados ---")
    for img in images:
        print(f"Nome: '{img[0]}' | Cor: '{img[1]}'")
        
    conn.close()

if __name__ == "__main__":
    check_colors()
