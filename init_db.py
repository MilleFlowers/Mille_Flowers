import os

# Configuração da Base de Dados (Configurável via variável de ambiente para o Render)
DATABASE = os.environ.get('DATABASE_URL', 'database.db')
if DATABASE.startswith("sqlite:///"):
    DATABASE = DATABASE.replace("sqlite:///", "")
DATABASE = os.environ.get('DATABASE_PATH', DATABASE)

def criar_bd():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    # ---------------- TABELA PRODUTOS ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS produtos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        cor TEXT NOT NULL,
        preco REAL NOT NULL,
        imagem TEXT NOT NULL,
        imagem_blob BLOB,
        imagem_mimetype TEXT,
        esgotado INTEGER DEFAULT 0,
        cores_esgotadas TEXT DEFAULT ''
    );
    """)
    # ---------------- TABELA CORES ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL UNIQUE
    )
    """)

    # ---------------- TABELA USUARIOS ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        senha TEXT NOT NULL
    )
    """)

    # ---------------- TABELA PEDIDOS ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS pedidos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER,
        nome_cliente TEXT,
        email TEXT,
        produtos TEXT,
        morada TEXT,
        telefone TEXT,
        metodo_pagamento TEXT,
        valor_total REAL,
        status TEXT DEFAULT 'pendente',
        stripe_session_id TEXT,
        data TEXT
    )
    """)

    # ---------------- TABELA AVALIACOES ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS avaliacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        produto_id INTEGER NOT NULL,
        usuario_nome TEXT NOT NULL,
        nota INTEGER NOT NULL,
        comentario TEXT,
        data TEXT NOT NULL
    )
    """)

    # ---------------- TABELA COMPRAS ----------------
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS compras (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        produto_id INTEGER NOT NULL,
        data TEXT NOT NULL
    )
    """)

    # Limpa produtos antigos (opcional)
    cursor.execute("DELETE FROM produtos")

    # Inserir produtos iniciais
    produtos = [
        ("Lavanda","Roxo",1.50,"lavanda.jpeg"),
        ("Rosa","Vermelho",3.00,"rosa.jpeg"),
        ("Lotus","Rosa",4.00,"lotus.jpeg"),
        ("Tulipa","Amarelo",4.00,"tulipa.jpeg"),
        ("Lírio","Rosa",4.00,"lirio.jpeg"),
        ("Gerbera","Rosa",4.00,"gerbera.jpeg"),
        ("Girassol","Amarelo",5.00,"girassol.jpeg"),
        ("Margarida","Branco",5.00,"margarida.jpeg"),
        ("Caneta","Preto",8.00,"caneta.jpeg"),
        ("Chaveiro","Azul",2.00,"chaveiro.jpeg"),
        ("Imã","Branco",3.00,"ima.jpeg")
    ]

    cursor.executemany(
        "INSERT INTO produtos (nome, cor, preco, imagem) VALUES (?, ?, ?, ?)",
        produtos
    )

    # Inserir cores iniciais (as do default)
    cores_default = [
        ("vermelho",), ("vermelho bordo",), ("borgonha",), ("laranja",), ("dourado",), ("amarelo",),
        ("amarelo manteiga",), ("verde",), ("azul claro",), ("azul",), ("azul escuro",), ("roxo",), ("lilas",),
        ("rosa claro",), ("rosa",), ("rosa escuro",), ("castanho",), ("preto",), ("cinza",), ("branco",),
        ("normal",)
    ]
    cursor.executemany("INSERT OR IGNORE INTO cores (nome) VALUES (?)", cores_default)

    conn.commit()
    conn.close()

    print("Base de dados criada com sucesso!")

if __name__ == "__main__":
    criar_bd()