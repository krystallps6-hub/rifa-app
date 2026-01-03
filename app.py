import os
import sqlite3
from datetime import timedelta
from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash
from PIL import Image, ImageDraw, ImageFont
import io
import math

# ---------------- CONFIG ----------------

APP_PASSWORD = os.environ.get("RIFA_PASSWORD", "rifa2025")
DB_PATH = "rifa.db"

CARTELA_SIZE = 60

app = Flask(__name__)
app.secret_key = "chave-super-secreta"
app.permanent_session_lifetime = timedelta(hours=12)

# ---------------- DB ----------------

def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            number INTEGER PRIMARY KEY,
            buyer_name TEXT,
            sold INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Garante pelo menos a primeira cartela (1 a 60)
    for n in range(1, CARTELA_SIZE + 1):
        cur.execute(
            "INSERT OR IGNORE INTO tickets(number, buyer_name, sold) VALUES (?, '', 0)",
            (n,)
        )

    conn.commit()
    conn.close()

@app.before_request
def ensure_db():
    if not os.path.exists(DB_PATH):
        init_db()

def logged_in():
    return session.get("logged_in") is True

# ---------------- HELPERS ----------------

def get_last_number():
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT MAX(number) FROM tickets")
    max_number = cur.fetchone()[0] or 0
    conn.close()
    return max_number

def get_last_cartela():
    return math.ceil(get_last_number() / CARTELA_SIZE) or 1

def cartela_range(cartela):
    start = (cartela - 1) * CARTELA_SIZE + 1
    end = cartela * CARTELA_SIZE
    return start, end

# ---------------- AUTH ----------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("index"))
        flash("Senha incorreta")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------- APP ----------------

@app.route("/")
def index():
    if not logged_in():
        return redirect(url_for("login"))

    cartela = int(request.args.get("cartela", get_last_cartela()))
    start, end = cartela_range(cartela)

    conn = db_conn()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM tickets WHERE number BETWEEN ? AND ? ORDER BY number",
        (start, end)
    )
    tickets = cur.fetchall()

    cur.execute(
        "SELECT COUNT(*) FROM tickets WHERE sold = 1 AND number BETWEEN ? AND ?",
        (start, end)
    )
    sold_count = cur.fetchone()[0]

    conn.close()

    return render_template(
        "index.html",
        tickets=tickets,
        sold_count=sold_count,
        cartela=cartela,
        cartela_start=start,
        cartela_end=end,
        last_cartela=get_last_cartela()
    )

# ---------------- NOVA CARTELA ----------------

@app.route("/nova_cartela", methods=["POST"])
def nova_cartela():
    if not logged_in():
        return redirect(url_for("login"))

    last_number = get_last_number()
    start = last_number + 1
    end = start + CARTELA_SIZE - 1

    conn = db_conn()
    cur = conn.cursor()

    for n in range(start, end + 1):
        cur.execute(
            "INSERT INTO tickets(number, buyer_name, sold) VALUES (?, '', 0)",
            (n,)
        )

    conn.commit()
    conn.close()

    return redirect(url_for("index", cartela=get_last_cartela()))
# ---------------- RESET RIFA ----------------

@app.route("/reset_rifa", methods=["POST"])
def reset_rifa():
    if not logged_in():
        return redirect(url_for("login"))

    conn = db_conn()
    cur = conn.cursor()

    # Apaga TODOS os tickets
    cur.execute("DELETE FROM tickets")

    # Recria apenas a primeira cartela (1 a 60)
    for n in range(1, 61):
        cur.execute(
            "INSERT INTO tickets(number, buyer_name, sold) VALUES (?, '', 0)",
            (n,)
        )

    conn.commit()
    conn.close()

    return redirect(url_for("index"))

# ---------------- SELL / UNSELL ----------------

@app.route("/sell", methods=["POST"])
def sell():
    number = int(request.form["number"])
    name = request.form.get("buyer_name", "")

    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE tickets SET sold=1, buyer_name=? WHERE number=?",
        (name, number)
    )
    conn.commit()
    conn.close()

    return redirect(request.referrer)

@app.route("/unsell", methods=["POST"])
def unsell():
    number = int(request.form["number"])

    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE tickets SET sold=0, buyer_name='' WHERE number=?",
        (number,)
    )
    conn.commit()
    conn.close()

    return redirect(request.referrer)
# ---------------- IMAGE (CARTELA) ----------------

@app.route("/image")
def image():
    if not logged_in():
        return redirect(url_for("login"))

    start = int(request.args.get("from"))
    end = int(request.args.get("to"))

    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM tickets WHERE number BETWEEN ? AND ? ORDER BY number",
        (start, end)
    )
    tickets = cur.fetchall()
    conn.close()

    COLS = 10
    CELL = 68
    total = len(tickets)
    ROWS = (total + COLS - 1) // COLS

    MARGIN_X = 90
    HEADER_HEIGHT = 280
    GAP_AFTER_GRID = 40
    PRIZE_HEIGHT = 260

    WIDTH = MARGIN_X * 2 + COLS * CELL
    HEIGHT = HEADER_HEIGHT + ROWS * CELL + GAP_AFTER_GRID + PRIZE_HEIGHT + 40

    TEXT_COLOR = "#2b2b2b"
    BORDER_COLOR = "#b8aa84"
    X_COLOR = "#c62828"

    background_path = os.path.join("static", "backgrounds", "fundo_base_2.png")
    img = Image.open(background_path).convert("RGB")
    img = img.resize((WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("arial.ttf", 40)
        font_sub = ImageFont.truetype("arial.ttf", 20)
        font_number = ImageFont.truetype("arial.ttf", 24)
    except:
        font_title = font_sub = font_number = ImageFont.load_default()

    # ===== TÍTULO ORIGINAL (PRESERVADO) =====
    title = "RIFA BENEFICENTE"
    subtitle = "Casa NZO NDANDALUNDA"
    price = f"Números {start} a {end}"

    tw = draw.textbbox((0, 0), title, font=font_title)[2]
    draw.text(((WIDTH - tw) / 2, 70), title, fill=TEXT_COLOR, font=font_title)

    sw = draw.textbbox((0, 0), subtitle, font=font_sub)[2]
    draw.text(((WIDTH - sw) / 2, 125), subtitle, fill=TEXT_COLOR, font=font_sub)

    pw = draw.textbbox((0, 0), price, font=font_sub)[2]
    draw.text(((WIDTH - pw) / 2, 155), price, fill=TEXT_COLOR, font=font_sub)

    start_y = HEADER_HEIGHT + 30

    for i, t in enumerate(tickets):
        col = i % COLS
        row = i // COLS

        x = MARGIN_X + col * CELL
        y = start_y + row * CELL

        draw.rectangle(
            [x + 6, y + 6, x + CELL - 6, y + CELL - 6],
            outline=BORDER_COLOR,
            width=2
        )

        text = str(t["number"])
        bbox = draw.textbbox((0, 0), text, font=font_number)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]

        cx = x + CELL / 2
        cy = y + CELL / 2

        draw.text((cx - w / 2, cy - h / 2), text, fill=TEXT_COLOR, font=font_number)

        if t["sold"]:
            size = CELL * 0.20
            draw.line([cx - size, cy - size, cx + size, cy + size], fill=X_COLOR, width=3)
            draw.line([cx + size, cy - size, cx - size, cy + size], fill=X_COLOR, width=3)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return send_file(
        buf,
        mimetype="image/png",
        as_attachment=True,
        download_name=f"rifa_{start}_{end}.png"
    )
# ---------------- LISTA TXT (POR CARTELA) ----------------

@app.route("/lista_txt")
def lista_txt():
    if not logged_in():
        return redirect(url_for("login"))

    cartela = int(request.args.get("cartela", get_last_cartela()))
    start, end = cartela_range(cartela)

    conn = db_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT number, buyer_name FROM tickets WHERE number BETWEEN ? AND ? ORDER BY number",
        (start, end)
    )
    rows = cur.fetchall()
    conn.close()

    lines = []
    for r in rows:
        num = str(r["number"]).zfill(3)
        name = r["buyer_name"].strip()
        lines.append(f"{num} — {name}" if name else f"{num} —")

    header = (
        f"🎟️ RIFA — CARTELA {cartela}\n"
        f"Números {start} a {end}\n\n"
    )

    content = header + "\n".join(lines)

    buf = io.BytesIO()
    buf.write(content.encode("utf-8"))
    buf.seek(0)

    return send_file(
        buf,
        mimetype="text/plain",
        as_attachment=True,
        download_name=f"cartela_{cartela}.txt"
    )

# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
