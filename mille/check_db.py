import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

def register():
    conn = sqlite3.connect("database.db")
    
    email = "test@example.com"
    senha_hash = generate_password_hash("password123")
    
    conn.execute("INSERT INTO usuarios (nome, email, senha) VALUES (?, ?, ?)",
                 ("Test User", email, senha_hash))
    conn.commit()
    
    # Try retrieving and checking
    conn.row_factory = sqlite3.Row
    user = conn.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()
    
    print("User Email:", user["email"])
    print("Password Check:", check_password_hash(user["senha"], "password123"))
    
    conn.close()

if __name__ == "__main__":
    register()
