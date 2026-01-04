import os
import math
import io
from datetime import timedelta

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor

from flask import (
    Flask, render_template, request, redirect,
    url_for, session, send_file, flash
)

from PIL import Image, ImageDraw, ImageFont

# ---------------- CONFIG ----------------

APP_PASSWORD = os.environ.get("RIFA_PASSWORD", "rifa2025")
DATABASE_URL = os.environ.get("DATABASE_URL")

CARTELA_SIZE = 60

app = Flask(__name__)
app.secret_key = "chave-super-secreta"
app.permanent_session_lifetime = timedelta(hours=12)

# ---------------- DB (POOL) ----------------

db_pool = SimpleConnectionPool(
    minconn=1,
    maxconn=5,
    dsn=DATABASE_URL
)

def db_conn():
    return db_pool.getconn()

def db_close(conn):
    db_pool.putconn(conn)

def init_db():
    conn = db_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            number INTEGER PRIMARY KEY,
            buyer_name TEXT,
            sold BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)

    for n in range(1, CARTELA_SIZE + 1):
        cur.execute("""
            INSERT INTO tickets (number, buyer_name, sold)
            VALUES (%s, '', FALSE)
            ON CONFLICT (number) DO NOTHING
        """, (n,))

    conn.commit()
    cur.close()
    db_close(conn)

# roda apenas uma vez
db_initialized = False

@app.before_request
def ensure_db():
    global db_initialized
    if not db_initialized:
        init_db()
        db_initialized = True

def logged_in():
    return session.get("logged_in") is True

# ---------------- HELPERS ----------------

def get_last_number():
    conn = db_conn()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(number), 0) FROM tickets")
    value = cur.fetchone()[0]
    cur.close()
    db_close(conn)
    return value

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
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT * FROM tickets
        WHERE number BETWEEN %s AND %s
        ORDER BY number
    """, (start, end))
    tickets = cur.fetchall()

    cur.execute("""
        SELECT COUNT(*) FROM tickets
        WHERE sold = TRUE AND number BETWEEN %s AND %s
    """, (start, end))
    sold_count = cur.fetchone()["count"]

    cur.close()
    db_close(conn)

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
        cur.execute("""
            INSERT INTO tickets (number, buyer_name, sold)
            VALUES (%s, '', FALSE)
        """, (n,))

    conn.commit()
    cur.close()
    db_close(conn)

    return redirect(url_for("index", cartela=get_last_cartela()))

# ---------------- RESET RIFA ----------------

@app.route("/reset_rifa", methods=["POST"])
def reset_rifa():
    if not logged_in():
        return redirect(url_for("login"))

    conn = db_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM tickets")

    for n in range(1, CARTELA_SIZE + 1):
        cur.execute("""
            INSERT INTO tickets (number, buyer_name, sold)
            VALUES (%s, '', FALSE)
        """, (n,))

    conn.commit()
    cur.close()
    db_close(conn)

    return redirect(url_for("index"))

# ---------------- SELL / UNSELL ----------------

@app.route("/sell", methods=["POST"])
def sell():
    number = int(request.form["number"])
    name = request.form.get("buyer_name", "")

    conn = db_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tickets
        SET sold = TRUE, buyer_name = %s
        WHERE number = %s
    """, (name, number))

    conn.commit()
    cur.close()
    db_close(conn)

    return redirect(request.referrer)

@app.route("/unsell", methods=["POST"])
def unsell():
    number = int(request.form["number"])

    conn = db_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE tickets
        SET sold = FALSE, buyer_name = ''
        WHERE number = %s
    """, (number,))

    conn.commit()
    cur.close()
    db_close(conn)

    return redirect(request.referrer)

# ---------------- IMAGE (CARTELA) ----------------

@app.route("/image")
def image():
    if not logged_in():
        return redirect(url_for("login"))

    start = int(request.args.get("from"))
    end = int(request.args.get("to"))

    conn = db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT * FROM tickets
        WHERE number BETWEEN %s AND %s
        ORDER BY number
    """, (start, end))
    tickets = cur.fetchall()

    cur.close()
    db_close(conn)

    COLS = 10
    CELL = 68
    ROWS = (len(tickets) + COLS - 1) // COLS

    MARGIN_X = 90
    HEADER_HEIGHT = 280
    PRIZE_HEIGHT = 260

    WIDTH = MARGIN_X * 2 + COLS * CELL
    HEIGHT = HEADER_HEIGHT + ROWS * CELL + PRIZE_HEIGHT + 40

    img = Image.open(
        os.path.join("static", "backgrounds", "fundo_base_2.png")
    ).resize((WIDTH, HEIGHT))

    draw = ImageDraw.Draw(img)

    FONTS = {
        "title": os.path.join("static", "fonts", "PlayfairDisplay-Regular.ttf"),
        "numbers": os.path.join("static", "fonts", "Montserrat-Regular.ttf"),
    }

    font_title = ImageFont.truetype(FONTS["title"], 50)
    font_sub = ImageFont.truetype(FONTS["title"], 26)
    font_number = ImageFont.truetype(FONTS["numbers"], 38)

    # título preservado
    title = "RIFA BENEFICENTE"
    subtitle = "Casa NZÓ DANDALUNDA"
    price = f"Números {start} a {end}"

    draw.text(((WIDTH - draw.textbbox((0,0), title, font=font_title)[2]) / 2, 70),
              title, fill="#2b2b2b", font=font_title)

    draw.text(((WIDTH - draw.textbbox((0,0), subtitle, font=font_sub)[2]) / 2, 125),
              subtitle, fill="#2b2b2b", font=font_sub)

    draw.text(((WIDTH - draw.textbbox((0,0), price, font=font_sub)[2]) / 2, 155),
              price, fill="#2b2b2b", font=font_sub)

    start_y = HEADER_HEIGHT + 30

    for i, t in enumerate(tickets):
        col = i % COLS
        row = i // COLS

        x = MARGIN_X + col * CELL
        y = start_y + row * CELL

        draw.rectangle(
            [x + 6, y + 6, x + CELL - 6, y + CELL - 6],
            outline="#b8aa84",
            width=2
        )

        text = str(t["number"])
        bbox = draw.textbbox((0, 0), text, font=font_number)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]

        cx = x + CELL / 2
        cy = y + CELL / 2

        draw.text((cx - w / 2, cy - h / 2), text, fill="#2b2b2b", font=font_number)

        if t["sold"]:
            size = CELL * 0.20
            draw.line([cx - size, cy - size, cx + size, cy + size], fill="#c62828", width=3)
            draw.line([cx + size, cy - size, cx - size, cy + size], fill="#c62828", width=3)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return send_file(
        buf,
        mimetype="image/png",
        as_attachment=True,
        download_name=f"rifa_{start}_{end}.png"
    )

# ---------------- LISTA TXT ----------------

@app.route("/lista_txt")
def lista_txt():
    if not logged_in():
        return redirect(url_for("login"))

    cartela = int(request.args.get("cartela", get_last_cartela()))
    start, end = cartela_range(cartela)

    conn = db_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT number, buyer_name
        FROM tickets
        WHERE number BETWEEN %s AND %s
        ORDER BY number
    """, (start, end))
    rows = cur.fetchall()

    cur.close()
    db_close(conn)

    lines = []
    for r in rows:
        num = str(r["number"]).zfill(3)
        name = r["buyer_name"].strip()
        lines.append(f"{num} — {name}" if name else f"{num} —")

    content = (
        f"🎟️ RIFA — CARTELA {cartela}\n"
        f"Números {start} a {end}\n\n"
        + "\n".join(lines)
    )

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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
