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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import secrets

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "mille_secret_key")

# Stripe API key (usa variável de ambiente em produção)
stripe.api_key = os.environ.get("STRIPE_API_KEY", "SUA_CHAVE_SECRETA_AQUI")

# Email do administrador
ADMIN_EMAIL = "filipenetocunha@gmail.com"

# Configurações SMTP - usar SEMPRE variáveis de ambiente no servidor (Render)
# Certifica-te de que definiste no Render:
# SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASS
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")

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

# ---------------- Database helper ----------------

def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

# ---------------- Admin helper ----------------

def is_admin():
    return session.get("email") == ADMIN_EMAIL

# ---------------- Email helper ----------------

def enviar_email(destinatario, assunto, corpo_html):
    """Envia um email formatado em HTML usando as configurações SMTP."""
    # Validar configuração SMTP (especialmente em ambiente Render)
    if not all([SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASS]):
        print(f"WARNING: Email não enviado para {destinatario} - SMTP não configurado corretamente (ver variáveis de ambiente).")
        return False

    msg = MIMEMultipart()
    msg['From'] = f"Mille Flowers <{SMTP_USER}>"
    msg['To'] = destinatario
    msg['Subject'] = assunto

    msg.attach(MIMEText(corpo_html, 'html'))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"ERROR: Erro ao enviar email: {e}")
        return False

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
            cores_esgotadas TEXT DEFAULT '',
            imagem_url TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS produto_imagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome_produto TEXT NOT NULL,
            cor TEXT NOT NULL,
            imagem_blob BLOB NOT NULL,
            imagem_mimetype TEXT NOT NULL,
            UNIQUE(nome_produto, cor)
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS newsletter (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            verificado INTEGER DEFAULT 0,
            token TEXT,
            data TEXT NOT NULL
        )
    """)
    # Migrações para newsletter
    try:
        conn.execute("ALTER TABLE newsletter ADD COLUMN verificado INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE newsletter ADD COLUMN token TEXT")
    except Exception:
        pass
    # Migração para imagens persistentes
    try:
        conn.execute("ALTER TABLE produtos ADD COLUMN imagem_blob BLOB")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE produtos ADD COLUMN imagem_mimetype TEXT")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE produtos ADD COLUMN imagem_url TEXT")
        conn.commit()
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
        for nome, cor, preco, img_name in produtos:
            img_path = os.path.join(app.static_folder, "img", img_name)
            blob = None
            mimetype = None
            if os.path.exists(img_path):
                print(f"DEBUG: Carregando BLOB para {img_name}")
                with open(img_path, "rb") as f:
                    blob = f.read()
                mimetype = mimetypes.guess_type(img_path)[0]
            else:
                print(f"WARNING: Imagem {img_path} não encontrada durante init_db")
            
            conn.execute(
                "INSERT INTO produtos (nome, cor, preco, imagem, imagem_blob, imagem_mimetype, imagem_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (nome, cor, preco, img_name, blob, mimetype, None)
            )
        
    # Migração automática: Se houver imagem no disco mas não no banco (BLOB), sincronizar.
    produtos_sem_blob = conn.execute("SELECT id, imagem FROM produtos WHERE imagem_blob IS NULL AND imagem IS NOT NULL").fetchall()
    if produtos_sem_blob:
        print(f"Sincronizando {len(produtos_sem_blob)} imagens para BLOB...")
        for p in produtos_sem_blob:
            img_path = os.path.join(app.static_folder, "img", p["imagem"])
            if os.path.exists(img_path):
                with open(img_path, "rb") as f:
                    blob = f.read()
                mimetype = mimetypes.guess_type(img_path)[0]
                conn.execute(
                    "UPDATE produtos SET imagem_blob = ?, imagem_mimetype = ? WHERE id = ?",
                    (blob, mimetype, p["id"])
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
    produto = conn.execute("SELECT imagem_blob, imagem_mimetype, imagem, imagem_url FROM produtos WHERE id = ?", (produto_id,)).fetchone()
    conn.close()

    if produto and produto["imagem_url"]:
        return redirect(produto["imagem_url"])

    if produto and produto["imagem_blob"]:
        from flask import Response
        return Response(produto["imagem_blob"], mimetype=produto["imagem_mimetype"] or "image/jpeg")
    
    # Fallback to static if no blob exists
    if produto and produto["imagem"]:
        return redirect(url_for('static', filename='img/' + produto["imagem"]))
    
    return "Imagem não encontrada", 404

@app.route("/produto/imagem_cor/<nome>/<cor>")
def serve_produto_imagem_cor(nome, cor):
    conn = get_db()
    # Normalize nome/cor parameters (e.g. from 'gerbera' to 'Gerbera', replacing underscores)
    nome = nome.capitalize()
    cor = cor.replace(' ', '_')
    
    imagem = conn.execute("SELECT imagem_blob, imagem_mimetype FROM produto_imagens WHERE nome_produto = ? AND cor = ?", (nome, cor)).fetchone()
    conn.close()

    if imagem and imagem["imagem_blob"]:
        from flask import Response
        return Response(imagem["imagem_blob"], mimetype=imagem["imagem_mimetype"] or "image/jpeg")

    return "Imagem não encontrada", 404

@app.route("/produto/<int:id>")
def produto(id):
    conn = get_db()
    produto = conn.execute("SELECT * FROM produtos WHERE id = ?", (id,)).fetchone()
    # Para produtos relacionados (exemplo: todos exceto o atual)
    produtos_rel = conn.execute("SELECT * FROM produtos WHERE id != ? LIMIT 4", (id,)).fetchall()
    
    # Fetch reviews
    avaliacoes = conn.execute("SELECT * FROM avaliacoes WHERE produto_id = ? ORDER BY id DESC", (id,)).fetchall()
    
    # Obter cores APENAS para este produto (se existirem na tabela produto_imagens)
    # Primeiro tentamos ver se há variantes no produto_imagens
    cores_produto_rows = conn.execute(
        "SELECT DISTINCT cor FROM produto_imagens WHERE nome_produto = ? ORDER BY cor",
        (produto["nome"].capitalize(),)
    ).fetchall()
    
    cores_especificas = [row["cor"] for row in cores_produto_rows]
    
    # Fallback ou se for cor única 'normal'
    if not cores_especificas or (len(cores_especificas) == 1 and cores_especificas[0] == 'normal'):
        tem_multi_cores = False
    else:
        tem_multi_cores = True
    
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
    return render_template("produto.html", 
                           produto=produto, 
                           produtos_rel=produtos_rel, 
                           avaliacoes=avaliacoes, 
                           cores_especificas=cores_especificas, 
                           tem_multi_cores=tem_multi_cores,
                           pode_avaliar=pode_avaliar)

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

@app.route("/admin/remover_avaliacao/<int:avaliacao_id>")
def remover_avaliacao(avaliacao_id):
    if not is_admin():
        flash("Acesso restrito ao administrador.", "error")
        return redirect(url_for("index"))

    conn = get_db()
    try:
        # Precisamos do id do produto para redirecionar de volta à página do produto
        avaliacao = conn.execute("SELECT produto_id FROM avaliacoes WHERE id = ?", (avaliacao_id,)).fetchone()
        if avaliacao:
            produto_id = avaliacao["produto_id"]
            conn.execute("DELETE FROM avaliacoes WHERE id = ?", (avaliacao_id,))
            conn.commit()
            flash("Avaliação removida com sucesso.", "success")
            return redirect(url_for("produto", id=produto_id))
        else:
            flash("Avaliação não encontrada.", "error")
            return redirect(url_for("admin"))
    except sqlite3.Error as e:
        flash(f"Erro ao remover a avaliação: {e}", "error")
        return redirect(url_for("admin"))
    finally:
        conn.close()

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
        "imagem_url": produto["imagem_url"],
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

@app.route("/admin/remover_newsletter/<int:sub_id>")
def remover_newsletter(sub_id):
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))
    
    conn = get_db()
    try:
        conn.execute("DELETE FROM newsletter WHERE id = ?", (sub_id,))
        conn.commit()
        flash("Subscritor removido com sucesso.")
    except Exception as e:
        flash(f"Erro ao remover subscritor: {e}")
    finally:
        conn.close()
    
    return redirect(url_for("admin"))

# ---------------- NEWSLETTER ----------------

@app.route("/newsletter/subscrever", methods=["POST"])
def newsletter_subscrever():
    email = request.form.get("email")
    if not email:
        return {"success": False, "message": "Email é obrigatório."}, 400
    
    conn = get_db()
    try:
        data_atual = datetime.now().strftime("%d/%m/%Y")
        token = secrets.token_urlsafe(32)
        
        # Verificar se já existe
        existente = conn.execute("SELECT * FROM newsletter WHERE email = ?", (email,)).fetchone()
        
        if existente:
            if existente["verificado"] == 1:
                return {"success": True, "message": "Este email já está subscrito e verificado."}
            else:
                # Atualizar token e re-enviar email
                conn.execute("UPDATE newsletter SET token = ? WHERE email = ?", (token, email))
        else:
            conn.execute("INSERT INTO newsletter (email, data, verificado, token) VALUES (?, ?, 0, ?)", 
                         (email, data_atual, token))
        
        conn.commit()
        
        # Enviar email de VERIFICAÇÃO (Double Opt-in)
        link_verificacao = url_for('newsletter_verificar', token=token, _external=True)
        assunto = "Confirme a sua subscrição — Mille Flowers ✦"
        corpo = f"""
        <div style="background-color: #fdfaf7; padding: 40px 20px; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border: 1px solid #f1e4d8;">
                <div style="background-color: #4a0404; padding: 30px; text-align: center;">
                    <h1 style="color: #d4af37; margin: 0; font-size: 24px; letter-spacing: 2px; text-transform: uppercase;">Mille Flowers</h1>
                </div>
                <div style="padding: 40px 30px; color: #333; line-height: 1.6; text-align: center;">
                    <h2 style="color: #4a0404; font-size: 20px; margin-bottom: 20px;">Falta apenas um passo!</h2>
                    <p>Recebemos o seu pedido para fazer parte do nosso jardim. Para garantir que foi você quem fez este pedido, por favor confirme o seu email clicando no botão abaixo:</p>
                    
                    <div style="text-align: center; margin: 40px 0;">
                        <a href="{link_verificacao}" style="background-color: #d4af37; color: white; padding: 15px 35px; text-decoration: none; border-radius: 50px; font-weight: bold; display: inline-block;">Confirmar Subscrição</a>
                    </div>
                    
                    <p style="font-size: 13px; color: #999;">Se não solicitou esta subscrição, pode ignorar este email com segurança.</p>
                </div>
                <div style="background-color: #fafafa; padding: 20px; text-align: center; border-top: 1px solid #eee;">
                    <p style="font-size: 11px; color: #bbb; margin: 0;">Mille Flowers Lisboa — Beleza Infinita.</p>
                </div>
            </div>
        </div>
        """
        enviar_email(email, assunto, corpo)
        
        return {"success": True, "message": "Enviámos um link de confirmação para o seu email!"}
    except Exception as e:
        return {"success": False, "message": f"Erro: {e}"}, 500
    finally:
        conn.close()

@app.route("/newsletter/verificar/<token>")
def newsletter_verificar(token):
    conn = get_db()
    subscritor = conn.execute("SELECT * FROM newsletter WHERE token = ?", (token,)).fetchone()
    
    if not subscritor:
        conn.close()
        flash("Link de verificação inválido ou expirado.")
        return redirect(url_for('index'))
    
    try:
        conn.execute("UPDATE newsletter SET verificado = 1, token = NULL WHERE id = ?", (subscritor["id"],))
        conn.commit()
        
        # Enviar email de Boas-Vindas final
        assunto = "Bem-vindo ao Jardim Mille Flowers! ✦"
        corpo = f"""
        <div style="background-color: #fdfaf7; padding: 40px 20px; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border: 1px solid #f1e4d8;">
                <div style="background-color: #4a0404; padding: 30px; text-align: center;">
                    <h1 style="color: #d4af37; margin: 0; font-size: 28px; letter-spacing: 2px; text-transform: uppercase;">Mille Flowers</h1>
                    <p style="color: #f1e4d8; margin: 5px 0 0; font-size: 12px; letter-spacing: 1px;">FLORES ETERNAS, BELEZA INFINITA</p>
                </div>
                <div style="padding: 40px 30px; color: #333; line-height: 1.6;">
                    <h2 style="color: #4a0404; font-size: 22px; margin-bottom: 20px; text-align: center;">Email Confirmado com Sucesso!</h2>
                    <p>Obrigado por confirmar o seu email. A partir de agora, serás o primeiro a receber novidades sobre as nossas criações e coleções exclusivas.</p>
                    
                    <div style="text-align: center; margin: 40px 0;">
                        <a href="{url_for('index', _external=True)}" style="background-color: #d4af37; color: white; padding: 15px 35px; text-decoration: none; border-radius: 50px; font-weight: bold; display: inline-block;">Visitar a Loja →</a>
                    </div>
                </div>
                <div style="background-color: #fafafa; padding: 20px; text-align: center; border-top: 1px solid #eee;">
                    <p style="font-size: 11px; color: #bbb; margin: 0;">Mille Flowers Lisboa — Beleza Infinita.</p>
                </div>
            </div>
        </div>
        """
        enviar_email(subscritor["email"], assunto, corpo)
        
        flash("Email verificado com sucesso! Bem-vindo à nossa newsletter.")
        return redirect(url_for('index'))
    except Exception as e:
        flash(f"Erro ao verificar email: {e}")
        return redirect(url_for('index'))
    finally:
        conn.close()

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
        telefone_loja = "932577476"  

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
    try:
        conn.execute("UPDATE pedidos SET status = 'pago' WHERE id = ?", (pedido_id,))
        conn.commit()
        flash("Pedido marcado como pago.")
    except sqlite3.Error as e:
        flash(f"Erro ao processar o pedido na base de dados: {e}")
    finally:
        conn.close()
        
    return redirect(url_for("admin"))

@app.route("/admin/marcar_enviado/<int:pedido_id>")
def marcar_enviado(pedido_id):
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))
        
    conn = get_db()
    try:
        conn.execute("UPDATE pedidos SET status = 'enviado' WHERE id = ?", (pedido_id,))
        conn.commit()
        flash("Pedido marcado como enviado.")
    except sqlite3.Error as e:
        flash(f"Erro ao processar o pedido na base de dados: {e}")
    finally:
        conn.close()
        
    return redirect(url_for("admin"))

@app.route("/admin/cancelar_pedido/<int:pedido_id>")
def cancelar_pedido(pedido_id):
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))
        
    conn = get_db()
    try:
        conn.execute("UPDATE pedidos SET status = 'cancelado' WHERE id = ?", (pedido_id,))
        conn.commit()
        flash("Pedido cancelado.")
    except sqlite3.Error as e:
        flash(f"Erro ao processar o pedido na base de dados: {e}")
    finally:
        conn.close()
        
    return redirect(url_for("admin"))

@app.route("/admin/remover_pedido/<int:pedido_id>")
def remover_pedido(pedido_id):
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))
        
    conn = get_db()
    try:
        conn.execute("DELETE FROM pedidos WHERE id = ?", (pedido_id,))
        conn.commit()
        flash("Pedido removido definitivamente com sucesso.")
    except sqlite3.Error as e:
        flash(f"Erro ao processar o pedido na base de dados: {e}")
    finally:
        conn.close()
        
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
    subscritores = conn.execute("SELECT * FROM newsletter ORDER BY id DESC").fetchall()
    conn.close()

    return render_template("admin.html", produtos=produtos, pedidos=pedidos, cores=cores, subscritores=subscritores)

@app.route("/admin/adicionar", methods=["POST"])
def adicionar_produto():
    if not is_admin():
        flash("Acesso restrito ao administrador.")
        return redirect(url_for("index"))

    nome = request.form.get("nome")
    preco = request.form.get("preco")
    cor_unica = request.form.get("cor_unica") == "1"
    
    # Listas de cores e ficheiros
    cores_ids = request.form.getlist("cores[]")
    files = request.files.getlist("imagens_upload[]")

    if not (nome and preco):
        flash("Nome e preço são obrigatórios.")
        return redirect(url_for("admin"))

    try:
        preco = float(preco)
    except ValueError:
        flash("Preço inválido.")
        return redirect(url_for("admin"))

    conn = get_db()
    try:
        if cor_unica:
            # Caso especial: Lavanda/Flor de cor única
            cores_nomes = ["normal"]
        else:
            # Obter nomes das cores a partir dos IDs
            cores_nomes = []
            for c_id in cores_ids:
                c_row = conn.execute("SELECT nome FROM cores WHERE id = ?", (c_id,)).fetchone()
                if c_row:
                    cores_nomes.append(c_row["nome"])
                else:
                    cores_nomes.append("desconhecida")

        if not cores_nomes or not files:
            flash("Deve adicionar pelo menos uma cor e uma imagem.")
            return redirect(url_for("admin"))

        # Inserir o produto principal (usando a primeira variante como padrão)
        primeira_cor = cores_nomes[0]
        primeiro_file = files[0]
        
        primeira_img_blob = primeiro_file.read()
        primeira_img_mimetype = primeiro_file.content_type
        primeiro_filename = secure_filename(primeiro_file.filename)
        
        # Resetar ponteiro para ler novamente se necessário (embora vamos usar os dados já lido)
        # Inserir na tabela produtos
        cursor = conn.execute(
            "INSERT INTO produtos (nome, cor, preco, imagem, imagem_blob, imagem_mimetype) VALUES (?, ?, ?, ?, ?, ?)",
            (nome, primeira_cor, preco, primeiro_filename, primeira_img_blob, primeira_img_mimetype)
        )
        produto_id = cursor.lastrowid

        # Inserir todas as variantes na tabela produto_imagens
        # O frontend troca imagens baseado em (nome_produto, cor)
        for i, cor_nome in enumerate(cores_nomes):
            if i < len(files):
                f = files[i]
                if i == 0:
                    blob = primeira_img_blob
                    mimetype = primeira_img_mimetype
                else:
                    blob = f.read()
                    mimetype = f.content_type
                
                if blob:
                    # Usar REPLACE para evitar duplicados se o admin tentar re-adicionar a mesma cor para o mesmo produto
                    # No init_db a tabela produto_imagens tem UNIQUE(nome_produto, cor)
                    conn.execute(
                        "INSERT OR REPLACE INTO produto_imagens (nome_produto, cor, imagem_blob, imagem_mimetype) VALUES (?, ?, ?, ?)",
                        (nome.capitalize(), cor_nome.replace(' ', '_'), blob, mimetype)
                    )

        conn.commit()
        flash(f"Produto '{nome}' e suas variantes adicionados com sucesso!")

        # Notificar subscritores verificados
        subscritores = conn.execute("SELECT email FROM newsletter WHERE verificado = 1").fetchall()
        if subscritores:
            # Novo: Design Chamativo para Notificação de Produto
            assunto = f"Acabou de Florescer: {nome}! ✦"
            corpo = f"""
            <div style="background-color: #fdfaf7; padding: 40px 20px; font-family: 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
                <div style="max-width: 600px; margin: 0 auto; background-color: #ffffff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.05); border: 1px solid #f1e4d8;">
                    <!-- Header -->
                    <div style="background-color: #4a0404; padding: 30px; text-align: center;">
                        <h1 style="color: #d4af37; margin: 0; font-size: 28px; letter-spacing: 2px; text-transform: uppercase;">Mille Flowers</h1>
                    </div>
                    
                    <!-- Feature Image Area -->
                    <div style="padding: 0; background-color: #f1e4d8; text-align: center;">
                        <div style="padding: 40px; background-color: #f1e4d8;">
                            <span style="display: inline-block; padding: 5px 15px; background: #d4af37; color: white; border-radius: 20px; font-size: 10px; font-weight: bold; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 20px;">NOVIDADE</span>
                            <h2 style="color: #4a0404; font-size: 32px; margin: 0;">{nome}</h2>
                            <p style="color: #7d635a; font-size: 16px; margin: 10px 0 0;">Uma nova peça exclusiva no nosso catálogo</p>
                        </div>
                    </div>
                    
                    <!-- Content -->
                    <div style="padding: 40px 30px; color: #333; line-height: 1.6; text-align: center;">
                        <p style="font-size: 18px; color: #4a0404;">Temos o prazer de anunciar uma nova criação artesanal.</p>
                        <p>Cada detalhe foi pensado para trazer elegância e charme ao seu espaço ou para ser o presente perfeito que nunca murcha.</p>
                        
                        <div style="background: #fdfaf7; border: 1px dashed #d4af37; padding: 20px; border-radius: 12px; margin: 30px 0;">
                            <p style="margin: 0; font-size: 20px; font-weight: bold; color: #4a0404;">€ {preco:.2f}</p>
                            <p style="margin: 5px 0 0; font-size: 14px; color: #666;">Peça Limitada e Artesanal</p>
                        </div>
                        
                        <div style="text-align: center; margin: 40px 0;">
                            <a href="{url_for('produto', id=0, _external=True).replace('0', '')}" style="background-color: #d4af37; color: white; padding: 18px 45px; text-decoration: none; border-radius: 50px; font-weight: bold; display: inline-block; font-size: 16px; box-shadow: 0 4px 15px rgba(212, 175, 55, 0.4);">Ver Detalhes na Loja</a>
                        </div>
                    </div>
                    
                    <!-- Footer -->
                    <div style="background-color: #fafafa; padding: 25px; text-align: center; border-top: 1px solid #eee;">
                        <p style="font-size: 12px; color: #999; margin: 0;">Mille Flowers Lisboa — Arte em Flor.</p>
                        <p style="font-size: 11px; color: #bbb; margin: 10px 0 0;">Não responda a este email automático.</p>
                    </div>
                </div>
            </div>
            """
            for s in subscritores:
                enviar_email(s['email'], assunto, corpo)

    except sqlite3.Error as e:
        flash(f"Erro ao adicionar produto na base de dados: {e}")
    finally:
        conn.close()

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
    try:
        conn.execute("DELETE FROM produtos WHERE id = ?", (produto_id,))
        conn.commit()
        flash("Produto removido com sucesso.")
    except sqlite3.Error as e:
        flash(f"Erro ao remover produto: {e}")
    finally:
        conn.close()

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
        imagem_url = request.form.get("imagem_url")
        imagem = request.form.get("imagem_text")
        
        # O campo `force_replace` já não é relevante
        force_replace = request.form.get("force_replace", "false")

        # Verifica se um arquivo foi enviado (imagem_upload)
        file = request.files.get("imagem_upload")
        imagem_blob = None
        imagem_mimetype = None

        if file and file.filename != "":
            filename = secure_filename(file.filename)
            imagem_blob = file.read()
            imagem_mimetype = file.content_type
            imagem = filename
            flash("Todos os campos são obrigatórios.")
            return redirect(url_for("editar_produto", produto_id=produto_id))

        try:
            preco = float(preco)
        except ValueError:
            flash("Preço inválido.")
            return redirect(url_for("editar_produto", produto_id=produto_id))

        try:
            if imagem_blob:
                conn.execute(
                    "UPDATE produtos SET nome = ?, cor = ?, preco = ?, imagem = ?, imagem_blob = ?, imagem_mimetype = ?, imagem_url = ? WHERE id = ?",
                    (nome, cor, preco, imagem, imagem_blob, imagem_mimetype, imagem_url, produto_id)
                )
            else:
                conn.execute(
                    "UPDATE produtos SET nome = ?, cor = ?, preco = ?, imagem_url = ? WHERE id = ?",
                    (nome, cor, preco, imagem_url, produto_id)
                )
            conn.commit()
            flash("Produto atualizado com sucesso.")
        except sqlite3.Error as e:
            flash(f"Erro ao atualizar produto: {e}")
        finally:
            conn.close()

        
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
    # Rota obsoleta - apenas redireciona para admin
    return redirect(url_for("admin"))

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
