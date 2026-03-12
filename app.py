import sqlite3
import os
import json
import mimetypes
from datetime import datetime
import stripe
from flask import Flask, render_template, request, redirect, session, url_for, flash
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import requests

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "mille_secret_key")

# Stripe API key (usa variável de ambiente em produção)
stripe.api_key = os.environ.get("STRIPE_API_KEY", "SUA_CHAVE_SECRETA_AQUI")

# Email do administrador
ADMIN_EMAIL = "filipenetocunha@gmail.com"

# ---------------- Context processor ----------------

@app.context_processor
def inject_globals():
    carrinho = session.get("carrinho", [])
    cart_count = sum(item["quantidade"] for item in carrinho)
    cart_total = sum(item["preco"] * item["quantidade"] for item in carrinho)
    logo_path = os.path.join(app.static_folder, "img", "logo.png")
    logo_exists = os.path.isfile(logo_path)
    return dict(
        cart_count=cart_count,
        cart_total=cart_total,
        logo_exists=logo_exists,
        now=datetime.now()
    )

# Configuração da Base de Dados (Configurável via variável de ambiente para o Render)
DATABASE = os.environ.get('DATABASE_URL', 'database.db')
if DATABASE.startswith("sqlite:///"):
    DATABASE = DATABASE.replace("sqlite:///", "")
DATABASE = os.environ.get('DATABASE_PATH', DATABASE)

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# ---------------- Admin helper ----------------

def is_admin():
    return session.get("email") == ADMIN_EMAIL

# ---------------- Init DB ----------------

def init_db():
    conn = get_db()
    conn.execute("""
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
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            senha TEXT NOT NULL
        )
    """)
    conn.execute("""
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

    # Migração: adicionar colunas novas se não existirem
    try:
        conn.execute("ALTER TABLE pedidos ADD COLUMN usuario_id INTEGER")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE pedidos ADD COLUMN nome_cliente TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE pedidos ADD COLUMN email TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE pedidos ADD COLUMN metodo_pagamento TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE pedidos ADD COLUMN valor_total REAL")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE pedidos ADD COLUMN status TEXT DEFAULT 'pendente'")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE pedidos ADD COLUMN stripe_session_id TEXT")
    except Exception:
        pass
    conn.execute("""
        CREATE TABLE IF NOT EXISTS avaliacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produto_id INTEGER NOT NULL,
            usuario_nome TEXT NOT NULL,
            nota INTEGER NOT NULL,
            comentario TEXT,
            data TEXT NOT NULL
        )
    """)
    # Migração para imagens persistentes
    try:
        conn.execute("ALTER TABLE produtos ADD COLUMN imagem_blob BLOB")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE produtos ADD COLUMN imagem_mimetype TEXT")
    except Exception:
        pass

    conn.execute("""
        CREATE TABLE IF NOT EXISTS compras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            produto_id INTEGER NOT NULL,
            data TEXT NOT NULL
        )
    """)

    # Opcional: inicializar produtos se estiver vazio
    produtos_count = conn.execute("SELECT COUNT(*) FROM produtos").fetchone()[0]
    if produtos_count == 0:
        produtos = [
            ("Lavanda", "normal", 1.50, "lavanda.jpeg"),
            ("Rosa", "normal", 3.00, "rosa.jpeg"),
            ("Lotus", "normal", 4.00, "lotus.jpeg"),
            ("Tulipa", "normal", 4.00, "tulipa.jpeg"),
            ("Gerbera", "normal", 4.00, "gerbera.jpeg"),
            ("Girassol", "normal", 5.00, "girassol.jpeg"),
            ("Margarida", "normal", 5.00, "margarida.jpeg"),
            ("Caneta", "normal", 8.00, "caneta.jpeg"),
            ("Chaveiro", "normal", 2.00, "chaveiro.jpeg"),
            ("Imã", "normal", 3.00, "ima.jpeg")
        ]
        conn.executemany(
            "INSERT INTO produtos (nome, cor, preco, imagem) VALUES (?, ?, ?, ?)",
            produtos
        )
        
    cores_count = conn.execute("SELECT COUNT(*) FROM cores").fetchone()[0]
    if cores_count == 0:
        cores_default = [
            ("vermelho",), ("vermelho bordo",), ("borgonha",), ("laranja",), ("dourado",), ("amarelo",),
            ("verde",), ("azul claro",), ("azul",), ("azul escuro",), ("roxo",), ("lilas",),
            ("rosa claro",), ("rosa",), ("rosa escuro",), ("castanho",), ("preto",), ("cinza",), ("branco",),
            ("normal",)
        ]
        conn.executemany("INSERT OR IGNORE INTO cores (nome) VALUES (?)", cores_default)

    conn.commit()
    conn.close()

# ---------------- Rotas ----------------

@app.route("/")
@app.route("/index")
def index():
    q = request.args.get("q", "").strip()
    conn = get_db()
    
    if q:
        produtos = conn.execute("SELECT * FROM produtos WHERE nome LIKE ?", ('%' + q + '%',)).fetchall()
    else:
        produtos = conn.execute("SELECT * FROM produtos").fetchall()
        
    conn.close()
    return render_template("index.html", produtos=produtos)

@app.route("/produto/imagem/<int:produto_id>")
def serve_produto_imagem(produto_id):
    conn = get_db()
    produto = conn.execute("SELECT imagem_blob, imagem_mimetype, imagem FROM produtos WHERE id = ?", (produto_id,)).fetchone()
    conn.close()

    if produto and produto["imagem_blob"]:
        from flask import Response
        return Response(produto["imagem_blob"], mimetype=produto["imagem_mimetype"] or "image/jpeg")
    
    # Fallback to static if no blob exists
    if produto and produto["imagem"]:
        return redirect(url_for('static', filename='img/' + produto["imagem"]))
    
    return "Imagem não encontrada", 404

@app.route("/produto/<int:id>")
def produto(id):
    conn = get_db()
    produto = conn.execute("SELECT * FROM produtos WHERE id = ?", (id,)).fetchone()
    # Para produtos relacionados (exemplo: todos exceto o atual)
    produtos_rel = conn.execute("SELECT * FROM produtos WHERE id != ? LIMIT 4", (id,)).fetchall()
    
    # Fetch reviews
    avaliacoes = conn.execute("SELECT * FROM avaliacoes WHERE produto_id = ? ORDER BY id DESC", (id,)).fetchall()
    
    # Fetch available colors for the select dropdown
    cores_rows = conn.execute("SELECT nome FROM cores ORDER BY nome").fetchall()
    cores_gerais = [row["nome"] for row in cores_rows]
    
    # Verificar se o utilizador logado comprou este produto
    pode_avaliar = False
    if "usuario_id" in session:
        compra = conn.execute(
            "SELECT id FROM compras WHERE usuario_id = ? AND produto_id = ?",
            (session["usuario_id"], id)
        ).fetchone()
        if compra:
            # Verificar se já não avaliou
            ja_avaliou = conn.execute(
                "SELECT id FROM avaliacoes WHERE produto_id = ? AND usuario_nome = ?",
                (id, session["usuario_nome"])
            ).fetchone()
            if not ja_avaliou:
                pode_avaliar = True
    
    conn.close()
    if not produto:
        return redirect(url_for("index"))
    return render_template("produto.html", produto=produto, produtos_rel=produtos_rel, avaliacoes=avaliacoes, cores_gerais=cores_gerais, pode_avaliar=pode_avaliar)

@app.route("/produto/<int:id>/avaliar", methods=["POST"])
def avaliar_produto(id):
    # Verificar se o utilizador está logado
    if "usuario_id" not in session:
        flash("Precisa de iniciar sessão para avaliar.", "error")
        return redirect(url_for("login"))
    
    # Verificar se o utilizador comprou este produto
    conn = get_db()
    compra = conn.execute(
        "SELECT id FROM compras WHERE usuario_id = ? AND produto_id = ?",
        (session["usuario_id"], id)
    ).fetchone()
    
    if not compra:
        conn.close()
        flash("Só pode avaliar produtos que já comprou.", "error")
        return redirect(url_for("produto", id=id))
    
    # Verificar se já avaliou
    ja_avaliou = conn.execute(
        "SELECT id FROM avaliacoes WHERE produto_id = ? AND usuario_nome = ?",
        (id, session["usuario_nome"])
    ).fetchone()
    
    if ja_avaliou:
        conn.close()
        flash("Já avaliou este produto.", "error")
        return redirect(url_for("produto", id=id))
    
    nota = request.form.get("nota", type=int)
    comentario = request.form.get("comentario", "")
    usuario_nome = session["usuario_nome"]
    data_atual = datetime.now().strftime("%d/%m/%Y")
    
    conn.execute(
        "INSERT INTO avaliacoes (produto_id, usuario_nome, nota, comentario, data) VALUES (?, ?, ?, ?, ?)",
        (id, usuario_nome, nota, comentario, data_atual)
    )
    conn.commit()
    conn.close()
    
    flash("Avaliação submetida com sucesso!", "success")
    return redirect(url_for("produto", id=id))

@app.route("/adicionar_carrinho", methods=["POST"])
def adicionar_carrinho():
    produto_id = request.form.get("produto_id")
    quantidade = int(request.form.get("quantidade", 1))
    cor = request.form.get("cor", "normal")

    conn = get_db()
    produto = conn.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,)).fetchone()
    conn.close()

    if not produto:
        flash("Produto não encontrado.")
        return redirect(url_for("index"))

    if produto["esgotado"] == 1:
        flash("Produto está esgotado e não pode ser adicionado ao carrinho.")
        return redirect(url_for("produto", id=produto_id))

    cores_esgotadas = []
    if produto["cores_esgotadas"]:
        cores_esgotadas = [c.strip().lower() for c in produto["cores_esgotadas"].split(",")]

    if cor.lower().replace("_", " ") in cores_esgotadas:
        flash("Esta cor está esgotada e não pode ser adicionada ao carrinho.")
        return redirect(url_for("produto", id=produto_id))

    if "carrinho" not in session:
        session["carrinho"] = []

    session["carrinho"].append({
        "id": produto["id"],
        "nome": produto["nome"],
        "preco": produto["preco"],
        "quantidade": quantidade,
        "imagem": produto["imagem"],
        "cor": cor
    })
    session.modified = True
    return redirect(url_for("carrinho"))

@app.route("/carrinho")
def carrinho():
    carrinho = session.get("carrinho", [])
    total = sum(item["preco"] * item["quantidade"] for item in carrinho)
    return render_template("carrinho.html", carrinho=carrinho, total=total)

@app.route("/remover/<int:index>")
def remover(index):
    if "carrinho" in session:
        if 0 <= index < len(session["carrinho"]):
            session["carrinho"].pop(index)
            session.modified = True
    return redirect(url_for("carrinho"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# ---------------- LOGIN ----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        senha_digitada = request.form.get("password")

        conn = get_db()
        user = conn.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user["senha"], senha_digitada):
            session["usuario_id"] = user["id"]
            session["usuario_nome"] = user["nome"]
            session["email"] = user["email"]  # <--- Guarda o email na sessão para admin
            return redirect(url_for("index"))

        flash("Email ou password inválidos. Tente novamente.")
        return redirect(url_for("login"))

    return render_template("login.html")

# ---------------- REGISTRO ----------------

@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        nome = request.form.get("nome")
        email = request.form.get("email")
        password = request.form.get("password")

        conn = get_db()
        usuario_existente = conn.execute("SELECT * FROM usuarios WHERE email = ?", (email,)).fetchone()

        if usuario_existente:
            conn.close()
            flash("Este email já está registado.")
            return redirect(url_for("registro"))

        senha_hash = generate_password_hash(password)

        conn.execute("INSERT INTO usuarios (nome, email, senha) VALUES (?, ?, ?)",
                     (nome, email, senha_hash))
        conn.commit()
        conn.close()

        flash("Registro efetuado com sucesso. Faça login.")
        return redirect(url_for("login"))

    return render_template("registro.html")

# ---------------- PAGAMENTO ----------------

@app.route("/pagamento")
def pagamento():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    carrinho = session.get("carrinho", [])
    if not carrinho:
        return redirect(url_for("carrinho"))

    total = sum(item["preco"] * item["quantidade"] for item in carrinho)
    return render_template("pagamento.html", carrinho=carrinho, total=total)

@app.route("/confirmar_pagamento", methods=["POST"])
def confirmar_pagamento():
    metodo = request.form.get("metodo_pagamento")
    carrinho = session.get("carrinho", [])
    if not carrinho:
        return redirect(url_for("carrinho"))

    total = sum(item["preco"] * item["quantidade"] for item in carrinho)
    portes = 0 if total >= 30 else 3.99
    valor_final = total + portes

    # Recolher dados do checkout
    nome_cliente = request.form.get("nome_cliente", "")
    email_cliente = request.form.get("email_cliente", "")
    morada = request.form.get("morada", "")
    telefone_cliente = request.form.get("telemovel_cliente", "")

    # Preparar lista de produtos como texto
    produtos_texto = ", ".join(
        f"{item['nome']} ({item['cor']}) x{item['quantidade']}" for item in carrinho
    )

    data_atual = datetime.now().strftime("%d/%m/%Y %H:%M")
    usuario_id = session.get("usuario_id")

    if metodo == "MB Way":
        order_id = f"ORDER{int(datetime.now().timestamp())}"
        telefone_loja = "912345678"  # Substitui pelo teu número real

        # Guardar pedido na base de dados
        conn = get_db()
        cursor = conn.execute(
            """INSERT INTO pedidos (usuario_id, nome_cliente, email, produtos, morada, telefone, metodo_pagamento, valor_total, status, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, nome_cliente, email_cliente, produtos_texto, morada, telefone_cliente, "MB Way", valor_final, "pendente", data_atual)
        )
        pedido_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Registar compras antes de limpar o carrinho
        _registar_compras()
        session.pop("carrinho", None)

        return render_template("pedido_registado.html", metodo="MB Way", valor=valor_final, order_id=order_id, telefone_loja=telefone_loja, pedido_id=pedido_id)

    elif metodo == "Cartão de Crédito":
        # Guardar pedido com status pendente
        conn = get_db()
        cursor = conn.execute(
            """INSERT INTO pedidos (usuario_id, nome_cliente, email, produtos, morada, telefone, metodo_pagamento, valor_total, status, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, nome_cliente, email_cliente, produtos_texto, morada, telefone_cliente, "Cartão", valor_final, "pendente", data_atual)
        )
        pedido_id = cursor.lastrowid
        conn.commit()
        conn.close()

        # Guardar pedido_id na sessão para associar ao Stripe
        session["pedido_pendente_id"] = pedido_id
        return redirect(url_for("create_checkout_session"), code=307)

    elif metodo == "Multibanco / ATM":
        # Guardar pedido com status pendente
        conn = get_db()
        cursor = conn.execute(
            """INSERT INTO pedidos (usuario_id, nome_cliente, email, produtos, morada, telefone, metodo_pagamento, valor_total, status, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (usuario_id, nome_cliente, email_cliente, produtos_texto, morada, telefone_cliente, "MB/ATM", valor_final, "pendente", data_atual)
        )
        pedido_id = cursor.lastrowid
        conn.commit()
        conn.close()

        _registar_compras()
        session.pop("carrinho", None)
        return render_template("pedido_registado.html", metodo="MB/ATM", valor=valor_final, pedido_id=pedido_id)

    else:
        return "Método inválido ou não implementado", 400

@app.route("/cartao")
def cartao():
    carrinho = session.get("carrinho", [])
    if not carrinho:
        return redirect(url_for("carrinho"))

    total = sum(item["preco"] * item["quantidade"] for item in carrinho)
    return render_template("cartao.html", carrinho=carrinho, total=total)

@app.route("/create-checkout-session", methods=["POST"])
def create_checkout_session():
    carrinho = session.get("carrinho", [])
    pedido_id = session.get("pedido_pendente_id")

    line_items = []
    for item in carrinho:
        line_items.append({
            "price_data": {
                "currency": "eur",
                "product_data": {
                    "name": item["nome"],
                },
                "unit_amount": int(item["preco"] * 100),
            },
            "quantity": item["quantidade"],
        })

    checkout_session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=line_items,
        mode="payment",
        success_url=url_for("sucesso", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=url_for("carrinho", _external=True),
        metadata={"pedido_id": str(pedido_id)} if pedido_id else {},
    )

    # Guardar stripe session id no pedido
    if pedido_id:
        conn = get_db()
        conn.execute("UPDATE pedidos SET stripe_session_id = ? WHERE id = ?", (checkout_session.id, pedido_id))
        conn.commit()
        conn.close()

    return redirect(checkout_session.url)

def _registar_compras():
    """Regista os produtos do carrinho na tabela compras para o utilizador logado."""
    if "usuario_id" not in session:
        return
    carrinho = session.get("carrinho", [])
    if not carrinho:
        return
    conn = get_db()
    data_atual = datetime.now().strftime("%d/%m/%Y")
    for item in carrinho:
        # Verificar se já existe registo desta compra para não duplicar
        existe = conn.execute(
            "SELECT id FROM compras WHERE usuario_id = ? AND produto_id = ?",
            (session["usuario_id"], item["id"])
        ).fetchone()
        if not existe:
            conn.execute(
                "INSERT INTO compras (usuario_id, produto_id, data) VALUES (?, ?, ?)",
                (session["usuario_id"], item["id"], data_atual)
            )
    conn.commit()
    conn.close()

@app.route("/sucesso")
def sucesso():
    stripe_session_id = request.args.get("session_id")
    pedido_id = session.pop("pedido_pendente_id", None)

    # Bloquear acesso direto — só funciona via Stripe redirect
    if not stripe_session_id or not pedido_id:
        flash("Acesso inválido.")
        return redirect(url_for("index"))

    metodo = "Cartão"

    # Verificar pagamento no Stripe
    try:
        stripe_session = stripe.checkout.Session.retrieve(stripe_session_id)
        if stripe_session.payment_status == "paid":
            conn = get_db()
            conn.execute("UPDATE pedidos SET status = 'pago', stripe_session_id = ? WHERE id = ?", (stripe_session_id, pedido_id))
            conn.commit()
            conn.close()
            metodo = "Cartão (pago com sucesso)"

            # Registar compras antes de limpar o carrinho
            _registar_compras()
            session.pop("carrinho", None)
            return render_template("sucesso.html", metodo=metodo)
        else:
            # Pagamento não confirmado pelo Stripe
            flash("O pagamento não foi confirmado. Tente novamente.")
            return redirect(url_for("carrinho"))
    except Exception:
        # Stripe indisponível ou session_id inválido
        flash("Não foi possível verificar o pagamento. Contacte-nos se já pagou.")
        return redirect(url_for("index"))

# ---------------- ADMIN: Gestão de Pedidos ----------------

@app.route("/admin/marcar_pago/<int:pedido_id>")
def marcar_pago(pedido_id):
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))
    conn = get_db()
    conn.execute("UPDATE pedidos SET status = 'pago' WHERE id = ?", (pedido_id,))
    conn.commit()
    conn.close()
    flash("Pedido marcado como pago.")
    return redirect(url_for("admin"))

@app.route("/admin/marcar_enviado/<int:pedido_id>")
def marcar_enviado(pedido_id):
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))
    conn = get_db()
    conn.execute("UPDATE pedidos SET status = 'enviado' WHERE id = ?", (pedido_id,))
    conn.commit()
    conn.close()
    flash("Pedido marcado como enviado.")
    return redirect(url_for("admin"))

@app.route("/admin/cancelar_pedido/<int:pedido_id>")
def cancelar_pedido(pedido_id):
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))
    conn = get_db()
    conn.execute("UPDATE pedidos SET status = 'cancelado' WHERE id = ?", (pedido_id,))
    conn.commit()
    conn.close()
    flash("Pedido cancelado.")
    return redirect(url_for("admin"))

# ---------------- ADMIN ----------------

@app.route("/admin")
def admin():
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))

    conn = get_db()
    produtos = conn.execute("SELECT * FROM produtos").fetchall()
    pedidos = conn.execute("SELECT * FROM pedidos").fetchall()
    cores = conn.execute("SELECT * FROM cores ORDER BY nome").fetchall()
    conn.close()

    return render_template("admin.html", produtos=produtos, pedidos=pedidos, cores=cores)

@app.route("/admin/adicionar", methods=["POST"])
def adicionar_produto():
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))

    nome = request.form.get("nome")
    cor = request.form.get("cor")
    preco = request.form.get("preco")

    imagem_blob = None
    imagem_mimetype = None
    file = request.files.get("imagem_upload")
    
    if file and file.filename != "":
        filename = secure_filename(file.filename)
        # Ler conteúdo para o banco de dados
        imagem_blob = file.read()
        imagem_mimetype = file.content_type
        
        # Opcional: Salvar em disco também como cache/fallback
        file.seek(0)
        upload_folder = os.path.join(app.root_path, 'static', 'img')
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        file.save(file_path)
        imagem = filename
    else:
        flash("A imagem do produto é obrigatória.")
        return redirect(url_for("admin"))

    if not (nome and cor and preco):
        flash("Todos os campos são obrigatórios.")
        return redirect(url_for("admin"))

    try:
        preco = float(preco)
    except ValueError:
        flash("Preço inválido.")
        return redirect(url_for("admin"))

    conn = get_db()
    conn.execute(
        "INSERT INTO produtos (nome, cor, preco, imagem, imagem_blob, imagem_mimetype) VALUES (?, ?, ?, ?, ?, ?)",
        (nome, cor, preco, imagem, imagem_blob, imagem_mimetype)
    )
    conn.commit()
    conn.close()

    flash("Produto adicionado com sucesso.")
    return redirect(url_for("admin"))

@app.route("/admin/esgotar/<int:produto_id>")
def esgotar_produto(produto_id):
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))

    conn = get_db()
    conn.execute("UPDATE produtos SET esgotado = 1 WHERE id = ?", (produto_id,))
    conn.commit()
    conn.close()

    flash("Produto marcado como esgotado.")
    return redirect(url_for("admin"))

@app.route("/admin/adicionar_cor", methods=["POST"])
def adicionar_cor():
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))

    nova_cor = request.form.get("nova_cor")
    
    if not nova_cor:
        flash("O nome da cor é obrigatório.")
        return redirect(url_for("admin"))

    # Vamos converter para minúsculas para padronizar
    nova_cor = nova_cor.strip().lower()

    conn = get_db()
    try:
        conn.execute("INSERT INTO cores (nome) VALUES (?)", (nova_cor,))
        conn.commit()
        flash("Nova cor adicionada com sucesso.")
    except sqlite3.IntegrityError:
        flash("Esta cor já existe na base de dados.")
    finally:
        conn.close()

    return redirect(url_for("admin"))

@app.route("/admin/remover_cor/<int:cor_id>")
def remover_cor(cor_id):
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))

    conn = get_db()
    conn.execute("DELETE FROM cores WHERE id = ?", (cor_id,))
    conn.commit()
    conn.close()

    flash("Cor removida com sucesso.")
    return redirect(url_for("admin"))

@app.route("/admin/reativar/<int:produto_id>")
def reativar_produto(produto_id):
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))

    conn = get_db()
    conn.execute("UPDATE produtos SET esgotado = 0 WHERE id = ?", (produto_id,))
    conn.commit()
    conn.close()

    flash("Produto reativado com sucesso.")
    return redirect(url_for("admin"))

@app.route("/admin/remover/<int:produto_id>")
def remover_produto(produto_id):
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))

    conn = get_db()
    conn.execute("DELETE FROM produtos WHERE id = ?", (produto_id,))
    conn.commit()
    conn.close()

    flash("Produto removido com sucesso.")
    return redirect(url_for("admin"))

@app.route("/admin/editar/<int:produto_id>", methods=["GET", "POST"])
def editar_produto(produto_id):
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))

    conn = get_db()
    produto = conn.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,)).fetchone()

    if request.method == "POST":
        nome = request.form.get("nome")
        cor = request.form.get("cor")
        preco = request.form.get("preco")
        imagem = request.form.get("imagem_text")
        
        # O campo `force_replace` indica que o usuário já confirmou que quer substituir
        force_replace = request.form.get("force_replace", "false")

        # Verifica se um arquivo foi enviado (imagem_upload)
        file = request.files.get("imagem_upload")
        imagem_blob = None
        imagem_mimetype = None

        if file and file.filename != "":
            filename = secure_filename(file.filename)
            upload_folder = os.path.join(app.root_path, 'static', 'img')
            os.makedirs(upload_folder, exist_ok=True)
            file_path = os.path.join(upload_folder, filename)
            
            # Se o ficheiro já existe e o utilizador ainda não confirmou substituição
            if os.path.exists(file_path) and force_replace != "true":
                # Salvar temporariamente caso ele queira confirmar e fechar
                # Guarda temporariamente
                temp_folder = os.path.join(app.root_path, 'static', 'tmp')
                os.makedirs(temp_folder, exist_ok=True)
                temp_path = os.path.join(temp_folder, filename)
                file.save(temp_path)
                
                # Redireciona para página de confirmação
                session['upload_pendente'] = {
                    'produto_id': produto_id,
                    'nome': nome,
                    'cor': cor,
                    'preco': preco,
                    'filename': filename,
                    'mimetype': file.content_type
                }
                return redirect(url_for('confirmar_substituicao'))
                
            else:
                # O utilizador forçou a substituição ou o ficheiro não existia
                imagem_blob = file.read()
                imagem_mimetype = file.content_type
                file.seek(0)
                file.save(file_path)
                imagem = filename

        # Se viemos de uma confirmação forçada (sem ficheiro no request, mas com forçar substituição)
        if force_replace == "true" and not file:
            filename = request.form.get("imagem_text")
            temp_path = os.path.join(app.root_path, 'static', 'tmp', filename)
            file_path = os.path.join(app.root_path, 'static', 'img', filename)
            
            if os.path.exists(temp_path):
                with open(temp_path, "rb") as f:
                    imagem_blob = f.read()
                imagem_mimetype = mimetypes.guess_type(filename)[0]
                # Move do tmp para o img
                os.replace(temp_path, file_path)
                imagem = filename

        if not (nome and cor and preco and imagem):
            flash("Todos os campos são obrigatórios.")
            return redirect(url_for("editar_produto", produto_id=produto_id))

        try:
            preco = float(preco)
        except ValueError:
            flash("Preço inválido.")
            return redirect(url_for("editar_produto", produto_id=produto_id))

        if imagem_blob:
            conn.execute(
                "UPDATE produtos SET nome = ?, cor = ?, preco = ?, imagem = ?, imagem_blob = ?, imagem_mimetype = ? WHERE id = ?",
                (nome, cor, preco, imagem, imagem_blob, imagem_mimetype, produto_id)
            )
        else:
            conn.execute(
                "UPDATE produtos SET nome = ?, cor = ?, preco = ? WHERE id = ?",
                (nome, cor, preco, produto_id)
            )
        conn.commit()
        conn.close()

        flash("Produto atualizado com sucesso.")
        
        # Limpar temp se existir
        session.pop('upload_pendente', None)
        
        return redirect(url_for("admin"))

    # Obter os nomes únicos e as cores atreladas a esta flor (como no gerir_cores)
    nomes_db = conn.execute("SELECT DISTINCT nome FROM produtos ORDER BY nome").fetchall()
    nomes_unicos = [row["nome"] for row in nomes_db]
    
    cores_por_flor = {
        'Caneta': ["vermelho", "verde", "azul_claro", "azul_escuro", "preto"],
        'default': [
            "vermelho", "vermelho bordo", "borgonha", "laranja", "dourado", "amarelo",
            "verde", "azul claro", "azul", "azul escuro", "roxo", "lilas",
            "rosa claro", "rosa", "rosa escuro", "castanho", "preto", "cinza", "branco"
        ]
    }
    flores_sem_cor = ['Lavanda', 'Girassol', 'Margarida']
    
    # We pass the full mapping as JSON to dynamically update the dropdown in JS
    # We still need a default list for the initial render (based on current product)
    if produto['nome'] in flores_sem_cor:
        cores_unicas = ["normal"]
    else:
        cores_unicas = cores_por_flor.get(produto['nome'], cores_por_flor['default'])

    conn.close()
    if not produto:
        flash("Produto não encontrado.")
        return redirect(url_for("admin"))

    return render_template("editar_produto.html", 
                           produto=produto, 
                           nomes_unicos=nomes_unicos, 
                           cores_unicas=cores_unicas,
                           cores_por_flor_json=json.dumps(cores_por_flor),
                           flores_sem_cor_json=json.dumps(flores_sem_cor))

@app.route("/admin/confirmar_substituicao", methods=["GET", "POST"])
def confirmar_substituicao():
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))

    # Verifica se há dados na sessão
    dados_pendentes = session.get('upload_pendente')
    if not dados_pendentes:
        flash("Nenhuma substituição pendente encontrada.")
        return redirect(url_for("admin"))

    if request.method == "POST":
        acao = request.form.get("acao")
        produto_id = dados_pendentes['produto_id']
        
        if acao == "cancelar":
            # Apagar a foto do temp e voltar atrás
            temp_path = os.path.join(app.root_path, 'static', 'tmp', dados_pendentes['filename'])
            if os.path.exists(temp_path):
                os.remove(temp_path)
            session.pop('upload_pendente', None)
            flash("Ação cancelada. A imagem não foi substituída.")
            return redirect(url_for("editar_produto", produto_id=produto_id))
            
        elif acao == "substituir":
            nome = dados_pendentes['nome']
            cor = dados_pendentes['cor']
            preco = dados_pendentes['preco']
            filename = dados_pendentes['filename']
            mimetype = dados_pendentes.get('mimetype') or mimetypes.guess_type(filename)[0]
            
            # Move out of temp and read blob
            temp_path = os.path.join(app.root_path, 'static', 'tmp', filename)
            file_path = os.path.join(app.root_path, 'static', 'img', filename)
            imagem_blob = None
            if os.path.exists(temp_path):
                with open(temp_path, "rb") as f:
                    imagem_blob = f.read()
                os.replace(temp_path, file_path)
            
            conn = get_db()
            conn.execute(
                "UPDATE produtos SET nome = ?, cor = ?, preco = ?, imagem = ?, imagem_blob = ?, imagem_mimetype = ? WHERE id = ?",
                (nome, cor, preco, filename, imagem_blob, mimetype, produto_id)
            )
            conn.commit()
            conn.close()
            
            session.pop('upload_pendente', None)
            flash("Imagem substituída e produto atualizado com sucesso!")
            return redirect(url_for("admin"))

    return render_template("confirmar_substituicao.html", dados=dados_pendentes)

@app.route("/admin/gerir_cores/<int:produto_id>", methods=["GET", "POST"])
def gerir_cores(produto_id):
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))

    conn = get_db()
    produto = conn.execute("SELECT * FROM produtos WHERE id = ?", (produto_id,)).fetchone()

    if not produto:
        conn.close()
        flash("Produto não encontrado.")
        return redirect(url_for("admin"))

    # Cores disponíveis mapeadas por tipo de flor (deve coincidir com as de produto.html)
    cores_por_flor = {
        'Caneta': ["vermelho", "verde", "azul_claro", "azul_escuro", "preto"],
        # Se a flor não estiver mapeada, usa uma lista base genérica ou apenas 'normal'
        'default': [
            "vermelho", "vermelho bordo", "borgonha", "laranja", "dourado", "amarelo",
            "verde", "azul claro", "azul", "azul escuro", "roxo", "lilas",
            "rosa claro", "rosa", "rosa escuro", "castanho", "preto", "cinza", "branco"
        ]
    }

    # As flores Lavanda, Girassol e Margarida não têm escolha de cor em produto.html
    # (são apenas 'normal', ou nem têm cor selecionável). Podemos tratar isso também.
    flores_sem_cor = ['Lavanda', 'Girassol', 'Margarida']

    if produto['nome'] in flores_sem_cor:
        cores_todas = [] # Não há gestão de cor para estas
    else:
        cores_todas = cores_por_flor.get(produto['nome'], cores_por_flor['default'])

    cores_esgotadas = []
    if produto['cores_esgotadas']:
        cores_esgotadas = [c.strip().lower() for c in produto['cores_esgotadas'].split(',')]

    if request.method == "POST":
        # Receber as cores marcadas como esgotadas no form
        esgotadas_selecionadas = request.form.getlist("cores_esgotadas")
        esgotadas_str = ",".join(esgotadas_selecionadas)

        conn.execute(
            "UPDATE produtos SET cores_esgotadas = ? WHERE id = ?",
            (esgotadas_str, produto_id)
        )
        conn.commit()
        conn.close()

        flash("Estoque de cores atualizado com sucesso!")
        return redirect(url_for("admin"))

    conn.close()
    return render_template("gerir_cores.html", produto=produto, cores_todas=cores_todas, cores_esgotadas=cores_esgotadas)

# ---------------- INICIALIZAÇÃO ----------------

# Inicializa a BD ao arrancar (importante para o Render)
init_db()

if __name__ == "__main__":
    app.run(debug=True)