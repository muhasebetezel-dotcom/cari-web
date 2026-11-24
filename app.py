import io
import os
import sqlite3
from functools import wraps
from datetime import datetime
from flask import (
    Flask, request, redirect, url_for,
    render_template_string, flash, session, send_file
)

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "cari_web.db")

KULLANICI_ADI = "admin"
SIFRE = "1234"

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "cari-web-panel-anahtari-2026")

TR_ORDER = "0123456789abcçdefgğhıijklmnoöpqrsştuüvwxyz"
TR_DICT = {ch: i for i, ch in enumerate(TR_ORDER)}


def tr_sort_key(text):
    if not text:
        return []
    s = str(text).lower().replace("İ", "i").replace("I", "ı")
    return [TR_DICT.get(c, 100 + ord(c)) for c in s]


def multi_keyword_match(query, *fields):
    if not query or not query.strip():
        return True
    keywords = query.lower().replace("İ", "i").replace("I", "ı").split()
    combined = " ".join(str(f or "") for f in fields).lower().replace("İ", "i").replace("I", "ı")
    return all(kw in combined for kw in keywords)


def money(val):
    try:
        v = float(val or 0.0)
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0,00"


def parse_num(val):
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s:
        return 0.0
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


app.jinja_env.filters["money"] = money


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cariler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kod TEXT UNIQUE NOT NULL,
            unvan TEXT NOT NULL,
            telefon TEXT,
            vergi_no TEXT,
            devir_tarihi TEXT,
            devir_tipi TEXT DEFAULT 'BORC',
            devir_tutari REAL DEFAULT 0.0,
            notlar TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS stoklar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kod TEXT UNIQUE NOT NULL,
            ad TEXT NOT NULL,
            birim TEXT DEFAULT 'Adet',
            kdv_orani REAL DEFAULT 20.0,
            satis_fiyati REAL DEFAULT 0.0,
            alis_fiyati REAL DEFAULT 0.0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS hareketler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cari_id INTEGER NOT NULL,
            tarih TEXT NOT NULL,
            belge_no TEXT,
            islem_turu TEXT NOT NULL,
            odeme_sekli TEXT,
            aciklama TEXT,
            borc REAL DEFAULT 0.0,
            alacak REAL DEFAULT 0.0,
            FOREIGN KEY (cari_id) REFERENCES cariler(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS fatura_kalemleri (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hareket_id INTEGER NOT NULL,
            stok_kodu TEXT,
            urun_adi TEXT NOT NULL,
            miktar REAL NOT NULL,
            birim TEXT DEFAULT 'Adet',
            birim_fiyat REAL NOT NULL,
            kdv_orani REAL DEFAULT 20.0,
            genel_toplam REAL NOT NULL,
            FOREIGN KEY (hareket_id) REFERENCES hareketler(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()


init_db()


def get_cari_bakiye(conn, cari_id):
    cur = conn.cursor()
    c = cur.execute("SELECT devir_tipi, devir_tutari FROM cariler WHERE id = ?", (cari_id,)).fetchone()
    if not c:
        return 0.0, 0.0, 0.0
    d_borc = float(c["devir_tutari"] or 0.0) if c["devir_tipi"] == "BORC" else 0.0
    d_alacak = float(c["devir_tutari"] or 0.0) if c["devir_tipi"] == "ALACAK" else 0.0
    h_borc, h_alacak = cur.execute(
        "SELECT COALESCE(SUM(borc), 0), COALESCE(SUM(alacak), 0) FROM hareketler WHERE cari_id = ?", (cari_id,)
    ).fetchone()
    t_borc = d_borc + float(h_borc or 0.0)
    t_alacak = d_alacak + float(h_alacak or 0.0)
    return t_borc, t_alacak, t_borc - t_alacak


LOGIN_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Giriş - Web Cari</title>
<style>
  body { margin:0; background:#0f2942; display:flex; justify-content:center; align-items:center; min-height:100vh; font-family:'Segoe UI',Arial,sans-serif; }
  .box { background:#fff; padding:28px; border-radius:10px; width:100%; max-width:360px; box-shadow:0 8px 24px rgba(0,0,0,0.25); }
  h2 { margin:0 0 16px; color:#0f2942; font-size:18px; }
  label { display:block; font-size:12px; font-weight:600; color:#475569; margin-bottom:4px; }
  input { width:100%; padding:10px; margin-bottom:12px; border:1px solid #cbd5e1; border-radius:6px; font-size:14px; }
  button { width:100%; padding:10px; background:#0284c7; color:#fff; border:none; border-radius:6px; font-size:15px; font-weight:600; cursor:pointer; }
  .err { background:#fee2e2; color:#991b1b; padding:8px; border-radius:6px; margin-bottom:12px; font-size:13px; }
</style>
</head>
<body>
  <form method="post" class="box">
    <h2>Cari Panel Girişi</h2>
    {% if err %}<div class="err">{{ err }}</div>{% endif %}
    <label>Kullanıcı Adı</label>
    <input name="kadi" required autofocus>
    <label>Şifre</label>
    <input type="password" name="sifre" required>
    <button type="submit">Giriş Yap</button>
  </form>
</body>
</html>"""

BASE_HTML = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Web Cari, Fatura & Ekstre</title>
<style>
  * { box-sizing: border-box; font-family: 'Segoe UI', Arial, sans-serif; }
  body { margin: 0; background: #f2f5f9; color: #1e293b; }
  header { background: #0f2942; color: #fff; padding: 14px 20px; display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 10px; }
  header h1 { margin: 0; font-size: 17px; }
  .ozet { font-size: 13px; color: #fde68a; font-weight: 600; }
  .top-links a { color: #e2e8f0; font-size: 12px; margin-left: 8px; text-decoration: none; background: rgba(255,255,255,0.12); padding: 5px 9px; border-radius: 4px; }
  nav { background: #1e3a5f; padding: 0 20px; display: flex; flex-wrap: wrap; gap: 4px; }
  nav a { color: #e2e8f0; text-decoration: none; padding: 10px 14px; font-size: 14px; font-weight: 600; border-bottom: 3px solid transparent; }
  nav a:hover, nav a.active { color: #fff; border-bottom-color: #38bdf8; background: rgba(255,255,255,0.06); }
  .container { max-width: 1360px; margin: 18px auto; padding: 0 16px; }
  .card { background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); margin-bottom: 16px; }
  h2 { margin-top: 0; font-size: 16px; color: #0f2942; border-bottom: 1px solid #e2e8f0; padding-bottom: 8px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; }
  label { display: block; font-size: 12px; font-weight: 600; color: #475569; margin-bottom: 4px; }
  input, select { width: 100%; padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 5px; font-size: 14px; }
  .filtre-kutu { background: #f8fafc; border: 1px solid #bae6fd; border-radius: 6px; padding: 10px; margin-bottom: 10px; }
  button, .btn { background: #0284c7; color: #fff; border: none; padding: 8px 13px; border-radius: 5px; font-size: 13px; font-weight: 600; cursor: pointer; text-decoration: none; display: inline-block; }
  button:hover, .btn:hover { background: #0369a1; }
  .btn-green { background: #15803d; }
  .btn-green:hover { background: #166534; }
  .btn-red { background: #b91c1c; padding: 5px 8px; font-size: 12px; }
  .btn-red:hover { background: #991b1b; }
  table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }
  th { background: #f1f5f9; color: #0f2942; text-align: left; padding: 9px 8px; border-bottom: 2px solid #cbd5e1; }
  td { padding: 8px; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .borclu { color: #b91c1c; font-weight: 700; }
  .alacakli { color: #15803d; font-weight: 700; }
  .flash { background: #dcfce7; color: #14532d; padding: 10px 14px; border-radius: 6px; margin-bottom: 12px; font-weight: 600; }
  .kalem-row { display: grid; grid-template-columns: 2.6fr 1.6fr 0.8fr 0.8fr 1.1fr 0.7fr auto; gap: 8px; align-items: end; margin-bottom: 8px; }
  @media (max-width: 900px) { .kalem-row { grid-template-columns: 1fr 1fr; } }
  @media print { nav, .no-print, .top-links { display: none !important; } body { background: #fff; } .card { box-shadow: none; padding: 0; } }
</style>
</head>
<body>
<header>
  <h1>CARİ HESAP, FATURA & EKSTRE</h1>
  <div class="ozet">Alacağımız: {{ genel_alacak|money }} TL &nbsp;|&nbsp; Borcumuz: {{ genel_borc|money }} TL</div>
  <div class="top-links">
    <a href="{{ url_for('excel_aktar') }}">Excel Aktar</a>
    <a href="{{ url_for('yedek_indir') }}">DB Yedek</a>
    <a href="{{ url_for('logout') }}">Çıkış</a>
  </div>
</header>
<nav>
  <a href="{{ url_for('cariler') }}" class="{{ 'active' if active=='cariler' else '' }}">Cari & Devir</a>
  <a href="{{ url_for('stoklar') }}" class="{{ 'active' if active=='stoklar' else '' }}">Stoklar</a>
  <a href="{{ url_for('fatura') }}" class="{{ 'active' if active=='fatura' else '' }}">Fatura Kes</a>
  <a href="{{ url_for('tahsilat') }}" class="{{ 'active' if active=='tahsilat' else '' }}">Tahsilat / Ödeme</a>
  <a href="{{ url_for('ekstre') }}" class="{{ 'active' if active=='ekstre' else '' }}">Ekstre</a>
  <a href="{{ url_for('urun_dokumu') }}" class="{{ 'active' if active=='urun_dokumu' else '' }}">Aldığı Ürünler</a>
</nav>
<div class="container">
  {% for msg in get_flashed_messages() %}
    <div class="flash">{{ msg }}</div>
  {% endfor %}
  {{ content|safe }}
</div>
<script>
// Çoklu kelime (boşlukla ayrılmış) canlı filtreleme
function filtreSecim(aramaInputId, selectId, sayacId) {
  const inp = document.getElementById(aramaInputId);
  const sel = document.getElementById(selectId);
  if (!inp || !sel) return;
  const kelimeler = inp.value.toLocaleLowerCase('tr').trim().split(/\s+/).filter(Boolean);
  let gorunen = 0;
  for (let i = 0; i < sel.options.length; i++) {
    const opt = sel.options[i];
    if (i === 0 && opt.value === "") { opt.hidden = false; continue; }
    const metin = (opt.dataset.ara || opt.text).toLocaleLowerCase('tr');
    const eslesiyor = kelimeler.every(k => metin.includes(k));
    opt.hidden = !eslesiyor;
    if (eslesiyor) gorunen++;
  }
  if (sayacId && document.getElementById(sayacId)) {
    document.getElementById(sayacId).textContent = "(" + gorunen + " kayıt)";
  }
}
</script>
</body>
</html>"""


@app.route("/login", methods=["GET", "POST"])
def login():
    err = None
    if request.method == "POST":
        if request.form.get("kadi") == KULLANICI_ADI and request.form.get("sifre") == SIFRE:
            session["logged_in"] = True
            return redirect(url_for("cariler"))
        err = "Kullanıcı adı veya şifre hatalı."
    return render_template_string(LOGIN_HTML, err=err)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/yedek-indir")
@login_required
def yedek_indir():
    if not os.path.exists(DB_PATH):
        flash("Veritabanı dosyası bulunamadı.")
        return redirect(url_for("cariler"))
    fname = f"cari_web_yedek_{datetime.now().strftime('%Y%m%d_%H%M')}.db"
    return send_file(DB_PATH, as_attachment=True, download_name=fname)


@app.route("/excel-sablon")
@login_required
def excel_sablon():
    if not HAS_OPENPYXL:
        flash("openpyxl yüklü değil.")
        return redirect(url_for("excel_aktar"))
    wb = openpyxl.Workbook()
    ws_c = wb.active
    ws_c.title = "cariler"
    ws_c.append(["kod", "unvan", "telefon", "vergi_no", "devir_tarihi", "devir_tipi", "devir_tutari", "notlar"])
    ws_c.append(["C-0001", "Örnek Müşteri A.Ş.", "05320000000", "1234567890", "2026-01-01", "BORC", 1500.00, "Eski devir"])

    ws_s = wb.create_sheet("stoklar")
    ws_s.append(["kod", "ad", "birim", "kdv_orani", "satis_fiyati", "alis_fiyati"])
    ws_s.append(["STK-0001", "Örnek Ürün", "Adet", 20, 250.00, 180.00])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name="cari_ve_stok_sablon.xlsx")


@app.route("/excel-aktar", methods=["GET", "POST"])
@login_required
def excel_aktar():
    ozet = None
    if request.method == "POST":
        if not HAS_OPENPYXL:
            flash("Excel okuma için openpyxl kurulu olmalıdır.")
            return redirect(url_for("excel_aktar"))

        dosya = request.files.get("excel_dosya")
        hedef = request.form.get("hedef", "otomatik")
        if not dosya or not dosya.filename:
            flash("Lütfen bir .xlsx dosyası seçin.")
            return redirect(url_for("excel_aktar"))

        wb = openpyxl.load_workbook(dosya, data_only=True)
        conn = get_db()
        cur = conn.cursor()
        cari_eklenen = cari_guncellenen = stok_eklenen = stok_guncellenen = 0

        def isle_cari_sayfasi(ws):
            nonlocal cari_eklenen, cari_guncellenen
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return
            baslik = [str(x or "").strip().lower() for x in rows[0]]
            start_idx = 1 if any(k in baslik for k in ("kod", "unvan", "ünvan", "cari", "bakiye", "borç", "borc", "alacak")) else 0
            for idx, r in enumerate(rows[start_idx:], start=start_idx + 1):
                vals = list(r) + [None] * 10
                kod = str(vals[0] or "").strip()
                unvan = str(vals[1] or "").strip()
                if not unvan:
                    continue
                if not kod:
                    kod = f"C-EX-{idx:04d}"
                tel = str(vals[2] or "").strip()
                vn = str(vals[3] or "").strip()
                d_tarih = str(vals[4] or "").strip()[:10] or datetime.now().strftime("%Y-%m-%d")
                raw_tip = str(vals[5] or "BORC").strip().upper()
                d_tutar = parse_num(vals[6])

                # Eğer devir yönü sütunu yoksa ve tutar negatifse ALACAK yap
                if "ALACAK" in raw_tip or raw_tip.startswith("A"):
                    d_tipi = "ALACAK"
                    d_tutar = abs(d_tutar)
                elif d_tutar < 0:
                    d_tipi = "ALACAK"
                    d_tutar = abs(d_tutar)
                else:
                    d_tipi = "BORC"

                notlar = str(vals[7] or "").strip()
                mevcut = cur.execute("SELECT id FROM cariler WHERE kod = ?", (kod,)).fetchone()
                if mevcut:
                    cur.execute("""
                        UPDATE cariler SET unvan=?, telefon=?, vergi_no=?, devir_tarihi=?, devir_tipi=?, devir_tutari=?, notlar=?
                        WHERE id=?
                    """, (unvan, tel, vn, d_tarih, d_tipi, d_tutar, notlar, mevcut["id"]))
                    cari_guncellenen += 1
                else:
                    cur.execute("""
                        INSERT INTO cariler (kod, unvan, telefon, vergi_no, devir_tarihi, devir_tipi, devir_tutari, notlar)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (kod, unvan, tel, vn, d_tarih, d_tipi, d_tutar, notlar))
                    cari_eklenen += 1

        def isle_stok_sayfasi(ws):
            nonlocal stok_eklenen, stok_guncellenen
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return
            baslik = [str(x or "").strip().lower() for x in rows[0]]
            start_idx = 1 if any(k in baslik for k in ("kod", "ad", "ürün", "urun", "stok", "fiyat", "birim")) else 0
            for idx, r in enumerate(rows[start_idx:], start=start_idx + 1):
                vals = list(r) + [None] * 8
                kod = str(vals[0] or "").strip()
                ad = str(vals[1] or "").strip()
                if not ad:
                    continue
                if not kod:
                    kod = f"STK-EX-{idx:04d}"
                birim = str(vals[2] or "Adet").strip() or "Adet"
                kdv = parse_num(vals[3]) if vals[3] not in (None, "") else 20.0
                satis = parse_num(vals[4])
                alis = parse_num(vals[5])

                mevcut = cur.execute("SELECT id FROM stoklar WHERE kod = ?", (kod,)).fetchone()
                if mevcut:
                    cur.execute("""
                        UPDATE stoklar SET ad=?, birim=?, kdv_orani=?, satis_fiyati=?, alis_fiyati=?
                        WHERE id=?
                    """, (ad, birim, kdv, satis, alis, mevcut["id"]))
                    stok_guncellenen += 1
                else:
                    cur.execute("""
                        INSERT INTO stoklar (kod, ad, birim, kdv_orani, satis_fiyati, alis_fiyati)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (kod, ad, birim, kdv, satis, alis))
                    stok_eklenen += 1

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            low = sheet_name.lower()
            if hedef == "cariler":
                isle_cari_sayfasi(ws)
            elif hedef == "stoklar":
                isle_stok_sayfasi(ws)
            else:
                if any(k in low for k in ("cari", "musteri", "müşteri", "devir", "bakiye")):
                    isle_cari_sayfasi(ws)
                elif any(k in low for k in ("stok", "urun", "ürün", "fiyat", "malzeme")):
                    isle_stok_sayfasi(ws)
                elif sheet_name == wb.sheetnames[0]:
                    isle_cari_sayfasi(ws)
                elif len(wb.sheetnames) > 1 and sheet_name == wb.sheetnames[1]:
                    isle_stok_sayfasi(ws)

        conn.commit()
        conn.close()
        ozet = (
            f"Aktarım tamamlandı -> Cari: {cari_eklenen} yeni, {cari_guncellenen} güncellendi | "
            f"Stok: {stok_eklenen} yeni, {stok_guncellenen} güncellendi."
        )
        flash(ozet)

    body = """
    <div class="card">
      <h2>Excel Dosyasından Cari ve Stok Aktarımı</h2>
      <p style="font-size:13px; color:#475569; margin-top:0;">
        Tek bir <b>.xlsx</b> dosyası içinde <b>cariler</b> ve <b>stoklar</b> sayfaları varsa otomatik algılar;
        istersen yalnızca cari veya yalnızca stok olarak da yükleyebilirsin. Mevcut kodlar güncellenir, yeniler eklenir.
      </p>
      <div style="margin-bottom:14px;">
        <a class="btn" href="{{ url_for('excel_sablon') }}">Örnek Şablon Excel İndir (.xlsx)</a>
      </div>
      <form method="post" enctype="multipart/form-data">
        <div class="grid">
          <div>
            <label>Excel Dosyası (.xlsx) *</label>
            <input type="file" name="excel_dosya" accept=".xlsx" required>
          </div>
          <div>
            <label>Aktarım Modu</label>
            <select name="hedef">
              <option value="otomatik">Otomatik (Sayfa adına göre Cari + Stok)</option>
              <option value="cariler">Sadece Cari & Devir</option>
              <option value="stoklar">Sadece Stok / Ürün</option>
            </select>
          </div>
        </div>
        <div style="margin-top:14px;">
          <button type="submit" class="btn-green">Excel'den Aktar</button>
        </div>
      </form>
      <div style="margin-top:16px; font-size:12px; color:#475569; background:#f8fafc; padding:10px; border-radius:6px;">
        <b>Cari Sütun Sırası:</b> A: Kod | B: Ünvan | C: Telefon | D: Vergi No | E: Devir Tarihi | F: Devir Yönü (BORC/ALACAK) | G: Devir Tutarı | H: Not<br>
        <b>Stok Sütun Sırası:</b> A: Kod | B: Ürün Adı | C: Birim | D: KDV % | E: Satış Fiyatı | F: Alış Fiyatı
      </div>
    </div>
    """
    return render_page("cariler", body, ozet=ozet)


def render_page(active, body_html, **ctx):
    conn = get_db()
    cur = conn.cursor()
    all_c = cur.execute("SELECT id FROM cariler").fetchall()
    genel_alacak = 0.0
    genel_borc = 0.0
    for r in all_c:
        _, _, b = get_cari_bakiye(conn, r["id"])
        if b > 0:
            genel_alacak += b
        elif b < 0:
            genel_borc += abs(b)
    conn.close()
    rendered_body = render_template_string(body_html, **ctx)
    return render_template_string(
        BASE_HTML, active=active, content=rendered_body,
        genel_alacak=genel_alacak, genel_borc=genel_borc
    )


@app.route("/", methods=["GET", "POST"])
@app.route("/cariler", methods=["GET", "POST"])
@login_required
def cariler():
    conn = get_db()
    cur = conn.cursor()
    if request.method == "POST":
        kod = request.form.get("kod", "").strip()
        unvan = request.form.get("unvan", "").strip()
        if not kod or not unvan:
            flash("Cari kodu ve ünvanı zorunludur.")
        else:
            devir_tarihi = request.form.get("devir_tarihi", "").strip() or datetime.now().strftime("%Y-%m-%d")
            devir_tipi = request.form.get("devir_tipi", "BORC")
            devir_tutari = parse_num(request.form.get("devir_tutari", "0"))
            try:
                cur.execute("""
                    INSERT INTO cariler (kod, unvan, telefon, vergi_no, devir_tarihi, devir_tipi, devir_tutari, notlar)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    kod, unvan, request.form.get("telefon", "").strip(),
                    request.form.get("vergi_no", "").strip(), devir_tarihi, devir_tipi,
                    devir_tutari, request.form.get("notlar", "").strip()
                ))
                conn.commit()
                flash(f"{unvan} kaydedildi.")
            except sqlite3.IntegrityError:
                flash(f"'{kod}' kodu zaten kayıtlı.")

    q = request.args.get("q", "")
    rows = sorted(cur.execute("SELECT * FROM cariler").fetchall(), key=lambda r: tr_sort_key(r["unvan"]))
    liste = []
    for r in rows:
        if not multi_keyword_match(q, r["kod"], r["unvan"], r["telefon"]):
            continue
        tb, ta, bak = get_cari_bakiye(conn, r["id"])
        liste.append({
            "id": r["id"], "kod": r["kod"], "unvan": r["unvan"], "telefon": r["telefon"] or "",
            "devir": float(r["devir_tutari"] or 0.0), "devir_tipi": r["devir_tipi"],
            "borc": tb, "alacak": ta, "bakiye": abs(bak),
            "yon": "Borçlu" if bak > 0 else ("Alacaklı" if bak < 0 else "Kapalı"),
            "is_borclu": bak > 0, "is_alacakli": bak < 0
        })

    next_kod = f"C-{len(rows) + 1:04d}"
    bugun = datetime.now().strftime("%Y-%m-%d")
    conn.close()

    body = """
    <div class="card">
      <h2>Yeni Cari & Eski Devir Girişi</h2>
      <form method="post">
        <div class="grid">
          <div><label>Cari Kodu *</label><input name="kod" value="{{ next_kod }}" required></div>
          <div><label>Cari Ünvanı *</label><input name="unvan" required placeholder="Örn: Yılmaz Ticaret"></div>
          <div><label>Telefon</label><input name="telefon"></div>
          <div><label>Vergi / TC No</label><input name="vergi_no"></div>
          <div><label>Devir Tarihi</label><input type="date" name="devir_tarihi" value="{{ bugun }}"></div>
          <div><label>Devir Yönü</label>
            <select name="devir_tipi">
              <option value="BORC">BORÇ (Bize Borçlu)</option>
              <option value="ALACAK">ALACAK (Biz Borçluyuz)</option>
            </select>
          </div>
          <div><label>Devir Tutarı (TL)</label><input name="devir_tutari" value="0,00"></div>
          <div><label>Not</label><input name="notlar"></div>
        </div>
        <div style="margin-top:12px;">
          <button type="submit" class="btn-green">Cariyi Kaydet</button>
          <a class="btn" href="{{ url_for('excel_aktar') }}" style="margin-left:6px;">Excel'den Toplu Aktar</a>
        </div>
      </form>
    </div>

    <div class="card">
      <h2>Kayıtlı Cariler ve Güncel Bakiyeler ({{ liste|length }} cari)</h2>
      <form method="get" style="display:flex; gap:8px; max-width:460px;">
        <input name="q" value="{{ q }}" placeholder="Çoklu kelime ara (kod, ünvan, tel)...">
        <button type="submit">Ara</button>
      </form>
      <table>
        <thead>
          <tr>
            <th>Kod</th><th>Ünvan</th><th>Telefon</th><th class="num">Devir</th>
            <th class="num">Borç</th><th class="num">Alacak</th><th class="num">Bakiye</th><th>İşlem</th>
          </tr>
        </thead>
        <tbody>
          {% for c in liste %}
          <tr>
            <td>{{ c.kod }}</td>
            <td><b>{{ c.unvan }}</b></td>
            <td>{{ c.telefon }}</td>
            <td class="num">{{ c.devir|money }} {{ '(B)' if c.devir_tipi=='BORC' else '(A)' }}</td>
            <td class="num">{{ c.borc|money }}</td>
            <td class="num">{{ c.alacak|money }}</td>
            <td class="num {{ 'borclu' if c.is_borclu else ('alacakli' if c.is_alacakli else '') }}">
              {{ c.bakiye|money }} ({{ c.yon }})
            </td>
            <td>
              <a class="btn" style="padding:5px 8px; font-size:12px;" href="{{ url_for('ekstre', cari_id=c.id) }}">Ekstre</a>
              <a class="btn" style="padding:5px 8px; font-size:12px; background:#0f766e;" href="{{ url_for('urun_dokumu', cari_id=c.id) }}">Ürünler</a>
              <a class="btn" style="padding:5px 8px; font-size:12px; background:#475569;" href="{{ url_for('devir_duzenle', cari_id=c.id) }}">Devir</a>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    """
    return render_page("cariler", body, liste=liste, next_kod=next_kod, bugun=bugun, q=q)


@app.route("/stoklar", methods=["GET", "POST"])
@login_required
def stoklar():
    conn = get_db()
    cur = conn.cursor()
    if request.method == "POST":
        kod = request.form.get("kod", "").strip()
        ad = request.form.get("ad", "").strip()
        if not kod or not ad:
            flash("Stok kodu ve ürün adı zorunludur.")
        else:
            birim = request.form.get("birim", "Adet").strip() or "Adet"
            kdv = parse_num(request.form.get("kdv_orani", "20"))
            satis = parse_num(request.form.get("satis_fiyati", "0"))
            alis = parse_num(request.form.get("alis_fiyati", "0"))
            try:
                cur.execute("""
                    INSERT INTO stoklar (kod, ad, birim, kdv_orani, satis_fiyati, alis_fiyati)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (kod, ad, birim, kdv, satis, alis))
                conn.commit()
                flash(f"{ad} stok kartı kaydedildi.")
            except sqlite3.IntegrityError:
                flash(f"'{kod}' stok kodu zaten mevcut.")

    q = request.args.get("q", "")
    rows = sorted(cur.execute("SELECT * FROM stoklar").fetchall(), key=lambda r: tr_sort_key(r["ad"]))
    liste = [r for r in rows if multi_keyword_match(q, r["kod"], r["ad"], r["birim"])]
    next_kod = f"STK-{len(rows) + 1:04d}"
    conn.close()

    body = """
    <div class="card">
      <h2>Yeni Stok / Ürün Kartı</h2>
      <form method="post">
        <div class="grid">
          <div><label>Stok Kodu *</label><input name="kod" value="{{ next_kod }}" required></div>
          <div><label>Ürün / Hizmet Adı *</label><input name="ad" required></div>
          <div><label>Birim</label><input name="birim" value="Adet"></div>
          <div><label>KDV %</label><input name="kdv_orani" value="20"></div>
          <div><label>Satış Fiyatı</label><input name="satis_fiyati" value="0,00"></div>
          <div><label>Alış Fiyatı</label><input name="alis_fiyati" value="0,00"></div>
        </div>
        <div style="margin-top:12px;">
          <button type="submit" class="btn-green">Stok Kaydet</button>
          <a class="btn" href="{{ url_for('excel_aktar') }}" style="margin-left:6px;">Excel'den Toplu Aktar</a>
        </div>
      </form>
    </div>

    <div class="card">
      <h2>Kayıtlı Stoklar ({{ liste|length }} ürün)</h2>
      <form method="get" style="display:flex; gap:8px; max-width:460px;">
        <input name="q" value="{{ q }}" placeholder="Çoklu kelime ara (kod, ürün adı)...">
        <button type="submit">Ara</button>
      </form>
      <table>
        <thead>
          <tr><th>Kod</th><th>Ürün Adı</th><th>Birim</th><th class="num">KDV %</th><th class="num">Satış Fiyatı</th><th class="num">Alış Fiyatı</th></tr>
        </thead>
        <tbody>
          {% for s in liste %}
          <tr>
            <td>{{ s.kod }}</td><td><b>{{ s.ad }}</b></td><td>{{ s.birim }}</td>
            <td class="num">%{{ s.kdv_orani|int }}</td>
            <td class="num">{{ s.satis_fiyati|money }}</td>
            <td class="num">{{ s.alis_fiyati|money }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    """
    return render_page("stoklar", body, liste=liste, next_kod=next_kod, q=q)


@app.route("/devir/<int:cari_id>", methods=["GET", "POST"])
@login_required
def devir_duzenle(cari_id):
    conn = get_db()
    cur = conn.cursor()
    cari = cur.execute("SELECT * FROM cariler WHERE id = ?", (cari_id,)).fetchone()
    if not cari:
        conn.close()
        return redirect(url_for("cariler"))
    if request.method == "POST":
        d_tarih = request.form.get("devir_tarihi", "").strip()
        d_tipi = request.form.get("devir_tipi", "BORC")
        d_tutar = parse_num(request.form.get("devir_tutari", "0"))
        notlar = request.form.get("notlar", "").strip()
        cur.execute("""
            UPDATE cariler SET devir_tarihi=?, devir_tipi=?, devir_tutari=?, notlar=? WHERE id=?
        """, (d_tarih, d_tipi, d_tutar, notlar, cari_id))
        conn.commit()
        conn.close()
        flash("Devir bilgisi güncellendi.")
        return redirect(url_for("cariler"))
    conn.close()
    body = """
    <div class="card">
      <h2>Devir Bilgisi Güncelle: {{ cari.kod }} - {{ cari.unvan }}</h2>
      <form method="post">
        <div class="grid">
          <div><label>Devir Tarihi</label><input type="date" name="devir_tarihi" value="{{ cari.devir_tarihi or '' }}"></div>
          <div><label>Devir Yönü</label>
            <select name="devir_tipi">
              <option value="BORC" {{ 'selected' if cari.devir_tipi=='BORC' else '' }}>BORÇ</option>
              <option value="ALACAK" {{ 'selected' if cari.devir_tipi=='ALACAK' else '' }}>ALACAK</option>
            </select>
          </div>
          <div><label>Devir Tutarı (TL)</label><input name="devir_tutari" value="{{ cari.devir_tutari|money }}"></div>
          <div><label>Not</label><input name="notlar" value="{{ cari.notlar or '' }}"></div>
        </div>
        <div style="margin-top:12px;"><button type="submit" class="btn-green">Güncelle</button></div>
      </form>
    </div>
    """
    return render_page("cariler", body, cari=cari)


@app.route("/fatura", methods=["GET", "POST"])
@login_required
def fatura():
    conn = get_db()
    cur = conn.cursor()
    if request.method == "POST":
        cari_id = int(request.form.get("cari_id", 0) or 0)
        islem_turu = request.form.get("islem_turu", "SATIS_FATURA")
        tarih = request.form.get("tarih", "").strip() or datetime.now().strftime("%Y-%m-%d")
        belge_no = request.form.get("belge_no", "").strip()
        aciklama = request.form.get("aciklama", "").strip() or ("Satış Faturası" if islem_turu == "SATIS_FATURA" else "Alış Faturası")

        kalemler = []
        genel_toplam = 0.0
        for skod, ad, mik, bir, fiy, kdv in zip(
            request.form.getlist("stok_kodu"), request.form.getlist("urun_adi"),
            request.form.getlist("miktar"), request.form.getlist("birim"),
            request.form.getlist("birim_fiyat"), request.form.getlist("kdv_orani")
        ):
            ad_s = (ad or "").strip()
            m_v = parse_num(mik)
            f_v = parse_num(fiy)
            k_v = parse_num(kdv)
            if ad_s and m_v > 0:
                satir_genel = round(m_v * f_v * (1.0 + k_v / 100.0), 2)
                genel_toplam = round(genel_toplam + satir_genel, 2)
                kalemler.append(((skod or "").strip(), ad_s, m_v, (bir or "Adet").strip(), f_v, k_v, satir_genel))

        if not cari_id or not kalemler:
            flash("Filtreden cari seçin ve en az bir ürün satırı girin.")
        else:
            borc = genel_toplam if islem_turu == "SATIS_FATURA" else 0.0
            alacak = 0.0 if islem_turu == "SATIS_FATURA" else genel_toplam
            cur.execute("""
                INSERT INTO hareketler (cari_id, tarih, belge_no, islem_turu, odeme_sekli, aciklama, borc, alacak)
                VALUES (?, ?, ?, ?, 'Açık Hesap', ?, ?, ?)
            """, (cari_id, tarih, belge_no, islem_turu, aciklama, borc, alacak))
            hid = cur.lastrowid
            for k in kalemler:
                cur.execute("""
                    INSERT INTO fatura_kalemleri (stok_kodu, hareket_id, urun_adi, miktar, birim, birim_fiyat, kdv_orani, genel_toplam)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (k[0], hid, k[1], k[2], k[3], k[4], k[5], k[6]))
            conn.commit()
            flash(f"Fatura kaydedildi. Toplam: {money(genel_toplam)} TL")
            conn.close()
            return redirect(url_for("ekstre", cari_id=cari_id))

    cariler_list = sorted(cur.execute("SELECT id, kod, unvan, telefon FROM cariler").fetchall(), key=lambda r: tr_sort_key(r["unvan"]))
    stoklar_list = sorted(cur.execute("SELECT * FROM stoklar").fetchall(), key=lambda r: tr_sort_key(r["ad"]))
    bugun = datetime.now().strftime("%Y-%m-%d")
    conn.close()

    body = """
    <div class="card">
      <h2>Fatura Kesimi (Filtreli Cari & Stok Seçimi)</h2>
      <form method="post">
        <div class="grid">
          <div><label>Fatura Türü</label>
            <select id="fat_tur" name="islem_turu" onchange="tumStoklariYenile()">
              <option value="SATIS_FATURA">SATIŞ FATURASI (Cari Borçlanır)</option>
              <option value="ALIS_FATURA">ALIŞ FATURASI (Cari Alacaklanır)</option>
            </select>
          </div>

          <div class="filtre-kutu">
            <label>Cari Ara & Filtreden Seç * <span id="cari_sayac">({{ cariler_list|length }} kayıt)</span></label>
            <input type="text" id="cari_ara" placeholder="Cari yaz, filtrelesin..." onkeyup="filtreSecim('cari_ara', 'cari_sec', 'cari_sayac')" style="margin-bottom:6px;">
            <select id="cari_sec" name="cari_id" required>
              <option value="">Cari seçin...</option>
              {% for c in cariler_list %}
                <option value="{{ c.id }}" data-ara="{{ c.kod }} {{ c.unvan }} {{ c.telefon or '' }}">{{ c.kod }} - {{ c.unvan }}</option>
              {% endfor %}
            </select>
          </div>

          <div><label>Tarih</label><input type="date" name="tarih" value="{{ bugun }}"></div>
          <div><label>Fatura No</label><input name="belge_no"></div>
          <div><label>Açıklama</label><input name="aciklama"></div>
        </div>

        <div class="filtre-kutu" style="margin-top:14px;">
          <label>Stok Ara & Filtreden Seç (Seçince satıra eklenir veya ilk satıra doldurulur) <span id="stok_sayac">({{ stoklar_list|length }} ürün)</span></label>
          <div style="display:flex; gap:8px; flex-wrap:wrap;">
            <input type="text" id="stok_ara" placeholder="Ürün adı veya stok kodu yaz, filtrelesin..." onkeyup="filtreSecim('stok_ara', 'stok_sec', 'stok_sayac')" style="flex:1; min-width:220px;">
            <select id="stok_sec" style="flex:2; min-width:260px;">
              <option value="">Stok seçin...</option>
              {% for s in stoklar_list %}
                <option value="{{ s.kod }}"
                        data-ara="{{ s.kod }} {{ s.ad }}"
                        data-ad="{{ s.ad }}"
                        data-birim="{{ s.birim }}"
                        data-kdv="{{ s.kdv_orani }}"
                        data-satis="{{ s.satis_fiyati }}"
                        data-alis="{{ s.alis_fiyati }}">
                  {{ s.kod }} - {{ s.ad }} ({{ s.satis_fiyati|money }} TL)
                </option>
              {% endfor %}
            </select>
            <button type="button" onclick="stoktanSatirEkle()">Stoku Satıra Aktar</button>
          </div>
        </div>

        <h3 style="margin-top:14px; font-size:14px;">Fatura Kalemleri</h3>
        <div id="kalemler">
          <div class="kalem-row">
            <div><label>Stok Kodu</label><input name="stok_kodu" placeholder="Kod"></div>
            <div><label>Ürün / Hizmet Adı</label><input name="urun_adi" placeholder="Ürün adı"></div>
            <div><label>Miktar</label><input name="miktar" value="1"></div>
            <div><label>Birim</label><input name="birim" value="Adet"></div>
            <div><label>Birim Fiyat</label><input name="birim_fiyat" placeholder="0,00"></div>
            <div><label>KDV %</label><input name="kdv_orani" value="20"></div>
            <div><button type="button" onclick="satirEkle()">+ Satır</button></div>
          </div>
        </div>

        <div style="margin-top:14px;">
          <button type="submit" class="btn-green">Faturayı Kaydet</button>
        </div>
      </form>
    </div>
    <script>
      function satirEkle(data = null) {
        const div = document.createElement('div');
        div.className = 'kalem-row';
        const sk = data ? data.kod : '';
        const ad = data ? data.ad : '';
        const bir = data ? data.birim : 'Adet';
        const fiy = data ? data.fiyat : '';
        const kdv = data ? data.kdv : '20';
        div.innerHTML = `
          <div><input name="stok_kodu" value="${sk}" placeholder="Kod"></div>
          <div><input name="urun_adi" value="${ad}" placeholder="Ürün adı"></div>
          <div><input name="miktar" value="1"></div>
          <div><input name="birim" value="${bir}"></div>
          <div><input name="birim_fiyat" value="${fiy}" placeholder="0,00"></div>
          <div><input name="kdv_orani" value="${kdv}"></div>
          <div><button type="button" class="btn-red" onclick="this.parentElement.parentElement.remove()">Sil</button></div>
        `;
        document.getElementById('kalemler').appendChild(div);
      }

      function stoktanSatirEkle() {
        const sel = document.getElementById('stok_sec');
        const opt = sel.options[sel.selectedIndex];
        if (!opt || !opt.value) return;
        const isSatis = document.getElementById('fat_tur').value === 'SATIS_FATURA';
        const hamFiyat = isSatis ? opt.dataset.satis : opt.dataset.alis;
        const fiyatFmt = Number(hamFiyat || 0).toLocaleString('tr-TR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
        const info = {
          kod: opt.dataset.ara.split(' ')[0],
          ad: opt.dataset.ad,
          birim: opt.dataset.birim || 'Adet',
          fiyat: fiyatFmt,
          kdv: opt.dataset.kdv || '20'
        };

        // İlk satır boşsa oraya doldur, doluysa yeni satır ekle
        const ilkSatir = document.querySelector('#kalemler .kalem-row');
        if (ilkSatir) {
          const adInp = ilkSatir.querySelector('input[name="urun_adi"]');
          if (adInp && !adInp.value.trim()) {
            ilkSatir.querySelector('input[name="stok_kodu"]').value = opt.value;
            adInp.value = info.ad;
            ilkSatir.querySelector('input[name="birim"]').value = info.birim;
            ilkSatir.querySelector('input[name="birim_fiyat"]').value = info.fiyat;
            ilkSatir.querySelector('input[name="kdv_orani"]').value = info.kdv;
            return;
          }
        }
        info.kod = opt.value;
        satirEkle(info);
      }
    </script>
    """
    return render_page("fatura", body, cariler_list=cariler_list, stoklar_list=stoklar_list, bugun=bugun)


@app.route("/tahsilat", methods=["GET", "POST"])
@login_required
def tahsilat():
    conn = get_db()
    cur = conn.cursor()
    if request.method == "POST":
        cari_id = int(request.form.get("cari_id", 0) or 0)
        yon = request.form.get("yon", "TAHSILAT")
        tutar = parse_num(request.form.get("tutar", "0"))
        tarih = request.form.get("tarih", "").strip() or datetime.now().strftime("%Y-%m-%d")
        sekil = request.form.get("odeme_sekli", "Nakit")
        belge = request.form.get("belge_no", "").strip()
        aciklama = request.form.get("aciklama", "").strip() or ("Tahsilat" if yon == "TAHSILAT" else "Ödeme")
        if cari_id and tutar > 0:
            borc = 0.0 if yon == "TAHSILAT" else tutar
            alacak = tutar if yon == "TAHSILAT" else 0.0
            cur.execute("""
                INSERT INTO hareketler (cari_id, tarih, belge_no, islem_turu, odeme_sekli, aciklama, borc, alacak)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (cari_id, tarih, belge, yon, sekil, aciklama, borc, alacak))
            conn.commit()
            flash("İşlem kaydedildi.")
        else:
            flash("Filtreden cari seçin ve geçerli tutar girin.")

    cariler_list = sorted(cur.execute("SELECT id, kod, unvan, telefon FROM cariler").fetchall(), key=lambda r: tr_sort_key(r["unvan"]))
    son_islemler = cur.execute("""
        SELECT h.*, c.unvan FROM hareketler h JOIN cariler c ON c.id = h.cari_id
        WHERE h.islem_turu IN ('TAHSILAT', 'ODEME')
        ORDER BY h.tarih DESC, h.id DESC LIMIT 50
    """).fetchall()
    bugun = datetime.now().strftime("%Y-%m-%d")
    conn.close()

    body = """
    <div class="card">
      <h2>Tahsilat / Ödeme</h2>
      <form method="post">
        <div class="grid">
          <div><label>İşlem Yönü</label>
            <select name="yon">
              <option value="TAHSILAT">TAHSİLAT</option>
              <option value="ODEME">ÖDEME</option>
            </select>
          </div>
          <div class="filtre-kutu">
            <label>Cari Ara & Filtreden Seç *</label>
            <input type="text" id="tah_cari_ara" placeholder="Cari yaz, filtrelesin..." onkeyup="filtreSecim('tah_cari_ara', 'tah_cari_sec')" style="margin-bottom:6px;">
            <select id="tah_cari_sec" name="cari_id" required>
              <option value="">Seçiniz...</option>
              {% for c in cariler_list %}
                <option value="{{ c.id }}" data-ara="{{ c.kod }} {{ c.unvan }} {{ c.telefon or '' }}">{{ c.kod }} - {{ c.unvan }}</option>
              {% endfor %}
            </select>
          </div>
          <div><label>Tarih</label><input type="date" name="tarih" value="{{ bugun }}"></div>
          <div><label>Ödeme Şekli</label>
            <select name="odeme_sekli">
              <option>Nakit</option><option>Havale / EFT</option><option>Kredi Kartı</option><option>Çek / Senet</option>
            </select>
          </div>
          <div><label>Belge No</label><input name="belge_no"></div>
          <div><label>Tutar (TL) *</label><input name="tutar" required></div>
          <div><label>Açıklama</label><input name="aciklama"></div>
        </div>
        <div style="margin-top:12px;"><button type="submit" class="btn-green">Kaydet</button></div>
      </form>
    </div>
    <div class="card">
      <h2>Son Tahsilat ve Ödemeler</h2>
      <table>
        <thead><tr><th>Tarih</th><th>Cari</th><th>Tür</th><th>Şekil</th><th>Belge</th><th class="num">Tutar</th><th>Açıklama</th></tr></thead>
        <tbody>
          {% for h in son_islemler %}
          <tr>
            <td>{{ h.tarih }}</td><td>{{ h.unvan }}</td>
            <td>{{ 'Tahsilat' if h.islem_turu=='TAHSILAT' else 'Ödeme' }}</td>
            <td>{{ h.odeme_sekli or '' }}</td><td>{{ h.belge_no or '' }}</td>
            <td class="num">{{ (h.alacak if h.islem_turu=='TAHSILAT' else h.borc)|money }}</td>
            <td>{{ h.aciklama or '' }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
    """
    return render_page("tahsilat", body, cariler_list=cariler_list, son_islemler=son_islemler, bugun=bugun)


@app.route("/hareket-sil/<int:hid>")
@login_required
def hareket_sil(hid):
    cari_id = request.args.get("cari_id", "")
    conn = get_db()
    conn.execute("DELETE FROM hareketler WHERE id = ?", (hid,))
    conn.commit()
    conn.close()
    flash("Hareket silindi.")
    return redirect(url_for("ekstre", cari_id=cari_id))


@app.route("/ekstre")
@login_required
def ekstre():
    conn = get_db()
    cur = conn.cursor()
    cariler_list = sorted(cur.execute("SELECT id, kod, unvan, telefon FROM cariler").fetchall(), key=lambda r: tr_sort_key(r["unvan"]))
    secili_id = int(request.args.get("cari_id", cariler_list[0]["id"] if cariler_list else 0) or 0)
    detay_goster = request.args.get("detay", "1") == "1"

    cari = cur.execute("SELECT * FROM cariler WHERE id = ?", (secili_id,)).fetchone() if secili_id else None
    satirlar = []
    running = 0.0
    t_borc = 0.0
    t_alacak = 0.0

    if cari:
        d_tutar = float(cari["devir_tutari"] or 0.0)
        d_b = d_tutar if cari["devir_tipi"] == "BORC" else 0.0
        d_a = d_tutar if cari["devir_tipi"] == "ALACAK" else 0.0
        running += (d_b - d_a)
        t_borc += d_b
        t_alacak += d_a
        satirlar.append({
            "hid": None, "tarih": cari["devir_tarihi"] or "", "belge": "DEVİR", "tur": "Devir",
            "aciklama": cari["notlar"] or "Eski dönem devri", "borc": d_b, "alacak": d_a,
            "bakiye": abs(running), "yon": "B" if running > 0 else ("A" if running < 0 else "-"),
            "is_detay": False
        })

        hareketler = cur.execute("SELECT * FROM hareketler WHERE cari_id = ? ORDER BY tarih ASC, id ASC", (secili_id,)).fetchall()
        tur_ad = {"SATIS_FATURA": "Satış Faturası", "ALIS_FATURA": "Alış Faturası", "TAHSILAT": "Tahsilat", "ODEME": "Ödeme"}
        for h in hareketler:
            b = float(h["borc"] or 0.0)
            a = float(h["alacak"] or 0.0)
            running += (b - a)
            t_borc += b
            t_alacak += a
            ack = h["aciklama"] or ""
            if h["odeme_sekli"] and h["islem_turu"] in ("TAHSILAT", "ODEME"):
                ack = f"[{h['odeme_sekli']}] {ack}"
            satirlar.append({
                "hid": h["id"], "tarih": h["tarih"], "belge": h["belge_no"] or "",
                "tur": tur_ad.get(h["islem_turu"], h["islem_turu"]), "aciklama": ack,
                "borc": b, "alacak": a, "bakiye": abs(running),
                "yon": "B" if running > 0 else ("A" if running < 0 else "-"), "is_detay": False
            })
            if detay_goster and h["islem_turu"] in ("SATIS_FATURA", "ALIS_FATURA"):
                for k in cur.execute("SELECT * FROM fatura_kalemleri WHERE hareket_id = ?", (h["id"],)).fetchall():
                    satirlar.append({
                        "hid": None, "tarih": "", "belge": "", "tur": "Ürün",
                        "aciklama": f"↳ {k['urun_adi']} ({money(k['miktar'])} {k['birim']} x {money(k['birim_fiyat'])} TL, KDV %{int(k['kdv_orani'])}) = {money(k['genel_toplam'])} TL",
                        "borc": None, "alacak": None, "bakiye": None, "yon": "", "is_detay": True
                    })

    conn.close()
    body = """
    <div class="card">
      <h2>Cari Ekstre</h2>
      <form method="get" class="no-print" style="display:flex; flex-wrap:wrap; gap:10px; align-items:end;">
        <div class="filtre-kutu" style="min-width:300px; margin-bottom:0;">
          <label>Cari Ara & Filtreden Seç</label>
          <input type="text" id="eks_cari_ara" placeholder="Cari yaz, filtrelesin..." onkeyup="filtreSecim('eks_cari_ara', 'eks_cari_sec')" style="margin-bottom:6px;">
          <select id="eks_cari_sec" name="cari_id">
            {% for c in cariler_list %}
              <option value="{{ c.id }}" data-ara="{{ c.kod }} {{ c.unvan }} {{ c.telefon or '' }}" {{ 'selected' if c.id==secili_id else '' }}>{{ c.kod }} - {{ c.unvan }}</option>
            {% endfor %}
          </select>
        </div>
        <div><label><input type="checkbox" name="detay" value="1" {{ 'checked' if detay_goster else '' }}> Ürün Detaylarını Göster</label></div>
        <div><button type="submit">Getir</button></div>
        <div><button type="button" class="btn-green" onclick="window.print()">Yazdır / PDF</button></div>
      </form>
      {% if cari %}
      <div style="margin-top:12px; font-weight:700;">{{ cari.kod }} - {{ cari.unvan }}</div>
      <table>
        <thead>
          <tr><th>Tarih</th><th>Belge</th><th>Tür</th><th>Açıklama</th><th class="num">Borç</th><th class="num">Alacak</th><th class="num">Bakiye</th><th>B/A</th><th class="no-print">Sil</th></tr>
        </thead>
        <tbody>
          {% for s in satirlar %}
          <tr style="{{ 'color:#475569; font-style:italic; font-size:12px;' if s.is_detay else '' }}">
            <td>{{ s.tarih }}</td><td>{{ s.belge }}</td><td>{{ s.tur }}</td><td>{{ s.aciklama }}</td>
            <td class="num">{{ s.borc|money if s.borc is not none else '' }}</td>
            <td class="num">{{ s.alacak|money if s.alacak is not none else '' }}</td>
            <td class="num"><b>{{ s.bakiye|money if s.bakiye is not none else '' }}</b></td>
            <td>{{ s.yon }}</td>
            <td class="no-print">
              {% if s.hid %}
                <a class="btn btn-red" href="{{ url_for('hareket_sil', hid=s.hid, cari_id=cari.id) }}" onclick="return confirm('Silinsin mi?')">X</a>
              {% endif %}
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      <div style="margin-top:12px; text-align:right; font-weight:700; font-size:15px;">
        Borç: {{ t_borc|money }} TL &nbsp;|&nbsp; Alacak: {{ t_alacak|money }} TL &nbsp;|&nbsp;
        Net: {{ (t_borc - t_alacak)|abs|money }} TL ({{ 'Borçlu' if (t_borc - t_alacak) > 0 else ('Alacaklı' if (t_borc - t_alacak) < 0 else 'Kapalı') }})
      </div>
      {% endif %}
    </div>
    """
    return render_page("ekstre", body, cariler_list=cariler_list, secili_id=secili_id, cari=cari, satirlar=satirlar, detay_goster=detay_goster, t_borc=t_borc, t_alacak=t_alacak)


@app.route("/urun-dokumu")
@login_required
def urun_dokumu():
    conn = get_db()
    cur = conn.cursor()
    cariler_list = sorted(cur.execute("SELECT id, kod, unvan, telefon FROM cariler").fetchall(), key=lambda r: tr_sort_key(r["unvan"]))
    stoklar_list = sorted(cur.execute("SELECT kod, ad FROM stoklar").fetchall(), key=lambda r: tr_sort_key(r["ad"]))
    secili_id = int(request.args.get("cari_id", 0) or 0)
    urun_q = request.args.get("urun", "").strip()

    sql = """
        SELECT fk.*, h.tarih, h.belge_no, h.islem_turu, c.unvan
        FROM fatura_kalemleri fk
        JOIN hareketler h ON h.id = fk.hareket_id
        JOIN cariler c ON c.id = h.cari_id
        WHERE 1=1
    """
    params = []
    if secili_id:
        sql += " AND h.cari_id = ?"
        params.append(secili_id)
    sql += " ORDER BY h.tarih DESC, fk.id DESC"

    rows = []
    top_miktar = 0.0
    top_tutar = 0.0
    for r in cur.execute(sql, params).fetchall():
        if not multi_keyword_match(urun_q, r["stok_kodu"], r["urun_adi"]):
            continue
        top_miktar += float(r["miktar"] or 0.0)
        top_tutar += float(r["genel_toplam"] or 0.0)
        rows.append(r)

    conn.close()
    body = """
    <div class="card">
      <h2>Aldığı Ürünler Dökümü</h2>
      <form method="get" style="display:flex; flex-wrap:wrap; gap:10px; align-items:end;">
        <div class="filtre-kutu" style="min-width:280px; margin-bottom:0;">
          <label>Cari Ara & Filtreden Seç</label>
          <input type="text" id="dok_cari_ara" placeholder="Cari yaz, filtrelesin..." onkeyup="filtreSecim('dok_cari_ara', 'dok_cari_sec')" style="margin-bottom:6px;">
          <select id="dok_cari_sec" name="cari_id">
            <option value="0">Tüm Cariler</option>
            {% for c in cariler_list %}
              <option value="{{ c.id }}" data-ara="{{ c.kod }} {{ c.unvan }} {{ c.telefon or '' }}" {{ 'selected' if c.id==secili_id else '' }}>{{ c.kod }} - {{ c.unvan }}</option>
            {% endfor %}
          </select>
        </div>

        <div class="filtre-kutu" style="min-width:280px; margin-bottom:0;">
          <label>Stok / Ürün Filtreden Seç veya Yaz</label>
          <select id="dok_stok_sec" onchange="if(this.value){document.getElementById('dok_urun_inp').value=this.value;}" style="margin-bottom:6px;">
            <option value="">Kayıtlı ürün seç (opsiyonel)...</option>
            {% for s in stoklar_list %}
              <option value="{{ s.ad }}">{{ s.kod }} - {{ s.ad }}</option>
            {% endfor %}
          </select>
          <input id="dok_urun_inp" name="urun" value="{{ urun_q }}" placeholder="Ürün ara...">
        </div>

        <div><button type="submit">Listele</button></div>
      </form>
      <table>
        <thead>
          <tr><th>Tarih</th><th>Fatura No</th><th>Tür</th><th>Cari</th><th>Kod</th><th>Ürün</th><th class="num">Miktar</th><th>Birim</th><th class="num">Fiyat</th><th class="num">Toplam</th></tr>
        </thead>
        <tbody>
          {% for r in rows %}
          <tr>
            <td>{{ r.tarih }}</td><td>{{ r.belge_no or '' }}</td>
            <td>{{ 'Satış' if r.islem_turu=='SATIS_FATURA' else 'Alış' }}</td>
            <td>{{ r.unvan }}</td><td>{{ r.stok_kodu or '' }}</td><td><b>{{ r.urun_adi }}</b></td>
            <td class="num">{{ r.miktar|money }}</td><td>{{ r.birim }}</td>
            <td class="num">{{ r.birim_fiyat|money }}</td><td class="num"><b>{{ r.genel_toplam|money }}</b></td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
      <div style="margin-top:12px; text-align:right; font-weight:700;">
        Toplam Miktar: {{ top_miktar|money }} &nbsp;|&nbsp; Genel Toplam: {{ top_tutar|money }} TL
      </div>
    </div>
    """
    return render_page("urun_dokumu", body, cariler_list=cariler_list, stoklar_list=stoklar_list, secili_id=secili_id, urun_q=urun_q, rows=rows, top_miktar=top_miktar, top_tutar=top_tutar)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
