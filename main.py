import os
import io
import uuid
import requests
import json
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from psycopg2.extras import RealDictCursor
import psycopg2
import openpyxl

app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")
TN_CLIENT_ID = os.getenv("TN_CLIENT_ID")
TN_CLIENT_SECRET = os.getenv("TN_CLIENT_SECRET")
TN_ACCESS_TOKEN = os.getenv("TN_ACCESS_TOKEN")
TN_STORE_ID = os.getenv("TN_STORE_ID")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS stock (
                    id SERIAL PRIMARY KEY,
                    nombre TEXT,
                    categoria TEXT,
                    talle TEXT,
                    color TEXT,
                    cantidad INTEGER DEFAULT 0,
                    imagen_url TEXT,
                    link_tienda TEXT,
                    creado_en TIMESTAMP DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS tokens_cambio (
                    token_id TEXT PRIMARY KEY,
                    orden_nro TEXT,
                    expira_at TIMESTAMP,
                    usado BOOLEAN DEFAULT FALSE,
                    remera_elegida_id INTEGER REFERENCES stock(id)
                );
            """)
            conn.commit()

init_db()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/auth/callback")
def auth_callback(code: str):
    response = requests.post(
        "https://www.tiendanube.com/apps/authorize/token",
        json={
            "client_id": TN_CLIENT_ID,
            "client_secret": TN_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code
        },
        headers={"User-Agent": "Samcro Stock (samcroremeras@gmail.com)"}
    )
    if response.status_code == 200:
        data = response.json()
        return {
            "ok": True,
            "TN_ACCESS_TOKEN": data.get("access_token"),
            "TN_STORE_ID": data.get("user_id"),
            "instruccion": "Copia estos dos valores y agregalos como variables en Railway"
        }
    return {"ok": False, "detalle": response.text}

class Remera(BaseModel):
    nombre: str
    categoria: str = ""
    talle: str
    color: str = ""
    cantidad: int = 0
    imagen_url: str = ""
    link_tienda: str = ""

@app.get("/api/stock")
def obtener_stock():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM stock ORDER BY id DESC;")
            return cur.fetchall()

@app.post("/api/stock")
def agregar_remera(r: Remera):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO stock (nombre, categoria, talle, color, cantidad, imagen_url, link_tienda)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;
            """, (r.nombre, r.categoria, r.talle, r.color, r.cantidad, r.imagen_url, r.link_tienda))
            nuevo_id = cur.fetchone()["id"]
            conn.commit()
            return {"ok": True, "id": nuevo_id}

@app.put("/api/stock/{id}")
def editar_remera(id: int, r: Remera):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE stock SET nombre=%s, categoria=%s, talle=%s, color=%s,
                cantidad=%s, imagen_url=%s, link_tienda=%s WHERE id=%s;
            """, (r.nombre, r.categoria, r.talle, r.color, r.cantidad, r.imagen_url, r.link_tienda, id))
            conn.commit()
            return {"ok": True}

@app.delete("/api/stock/{id}")
def eliminar_remera(id: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM stock WHERE id=%s;", (id,))
            conn.commit()
            return {"ok": True}

@app.post("/api/importar-excel")
async def importar_excel(file: UploadFile = File(...)):
    contents = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(contents))
    ws = wb.active
    headers = [str(cell.value).lower().strip() for cell in ws[1]]
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    with get_conn() as conn:
        with conn.cursor() as cur:
            contador = 0
            for row in rows:
                data = dict(zip(headers, row))
                if not data.get("nombre"):
                    continue
                cur.execute("""
                    INSERT INTO stock (nombre, categoria, talle, color, cantidad, imagen_url, link_tienda)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    str(data.get("nombre", "")),
                    str(data.get("categoria", "")),
                    str(data.get("talle", "")),
                    str(data.get("color", "")),
                    int(data.get("cantidad") or 0),
                    str(data.get("imagen_url", "")),
                    str(data.get("link_tienda", ""))
                ))
                contador += 1
            conn.commit()
    return {"ok": True, "importadas": contador}

@app.get("/api/exportar-excel")
def exportar_excel():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nombre, categoria, talle, color, cantidad, imagen_url, link_tienda FROM stock ORDER BY id DESC;")
            rows = cur.fetchall()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["nombre", "categoria", "talle", "color", "cantidad", "imagen_url", "link_tienda"])
    for r in rows:
        ws.append([r["nombre"], r["categoria"], r["talle"], r["color"], r["cantidad"], r["imagen_url"], r["link_tienda"]])
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=stock.xlsx"})

@app.post("/api/tokens")
def crear_token(orden_nro: str):
    token = str(uuid.uuid4())[:8]
    expira = datetime.now() + timedelta(hours=24)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tokens_cambio (token_id, orden_nro, expira_at)
                VALUES (%s, %s, %s);
            """, (token, orden_nro, expira))
            conn.commit()
    return {"token": token, "link": f"https://samcro-stock-production.up.railway.app/cambios/{token}"}

@app.get("/cambios/{token}", response_class=HTMLResponse)
def pagina_cambio(token: str):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tokens_cambio WHERE token_id=%s;", (token,))
            t = cur.fetchone()
    if not t:
        return "<h2>Link invalido.</h2>"
    if t["usado"]:
        return "<h2>Este link ya fue utilizado.</h2>"
    if datetime.now() > t["expira_at"]:
        return "<h2>Este link expiro.</h2>"

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM stock WHERE cantidad > 0 ORDER BY talle, nombre;")
            remeras = cur.fetchall()

    remeras_json = json.dumps([{
        "id": r["id"],
        "nombre": str(r["nombre"] or ""),
        "talle": str(r["talle"] or ""),
        "color": str(r["color"] or ""),
        "imagen_url": str(r["imagen_url"] or ""),
        "link_tienda": str(r["link_tienda"] or "")
    } for r in remeras])

    orden_nro = t["orden_nro"]
    token_id = t["token_id"]

    html = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Elegi tu cambio - Samcro Remeras</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#f5f5f5;color:#111;min-height:100vh}
header{background:#111;color:#fff;padding:1rem 1.5rem;text-align:center}
header h1{font-size:1rem;font-weight:600;letter-spacing:.05em}
header p{font-size:.8rem;color:#aaa;margin-top:2px}
.paso{display:none;padding:1.5rem}
.paso.activo{display:block}
.paso-titulo{font-size:1.1rem;font-weight:600;margin-bottom:.5rem}
.paso-sub{font-size:.85rem;color:#666;margin-bottom:1.5rem}
.talles{display:grid;grid-template-columns:repeat(4,1fr);gap:.5rem;margin-bottom:1.5rem}
.talle-btn{border:1.5px solid #ddd;border-radius:8px;padding:.75rem;text-align:center;font-size:.9rem;font-weight:500;background:#fff;cursor:pointer}
.talle-btn.sel{border-color:#111;background:#111;color:#fff}
.guia-link{font-size:.8rem;color:#2563eb;text-align:center;display:block;margin-bottom:1.5rem}
.btn-primary{width:100%;padding:.85rem;border-radius:8px;background:#111;color:#fff;border:none;font-size:.95rem;font-weight:500;cursor:pointer}
.btn-primary:disabled{background:#ccc}
.grid-remeras{display:grid;grid-template-columns:repeat(2,1fr);gap:.75rem;margin-bottom:1.5rem}
.remera-card{background:#fff;border-radius:10px;border:2px solid transparent;overflow:hidden;cursor:pointer}
.remera-card.sel{border-color:#111}
.remera-card img{width:100%;height:160px;object-fit:cover;background:#f0f0f0}
.remera-card .info{padding:.6rem}
.remera-card h3{font-size:.8rem;font-weight:600;margin-bottom:2px}
.remera-card p{font-size:.75rem;color:#666}
.confirm-box{background:#fff;border-radius:10px;padding:1rem;margin-bottom:1rem;border:1px solid #e5e5e5}
.confirm-box label{font-size:.75rem;color:#666}
.confirm-box p{font-size:.95rem;font-weight:500;margin-top:2px}
.success{text-align:center;padding:2rem 1.5rem}
.success-icon{width:60px;height:60px;border-radius:50%;background:#f0fdf4;display:flex;align-items:center;justify-content:center;margin:0 auto 1rem;font-size:1.5rem}
.timer{font-size:.75rem;color:#dc2626;text-align:center;margin-bottom:1rem}
.volver{background:none;border:none;color:#666;font-size:.85rem;cursor:pointer;margin-bottom:1rem;padding:0}
</style>
</head>
<body>
<header>
  <h1>SAMCRO REMERAS</h1>
  <p>Orden #""" + str(orden_nro) + """ &middot; Link valido por 24hs</p>
</header>

<div id="p1" class="paso activo">
  <p class="paso-titulo" style="margin-top:1rem">Que talle usas?</p>
  <p class="paso-sub">Si no estas seguro usa la guia de medidas.</p>
  <div class="talles" id="talles-grid"></div>
  <a class="guia-link" href="https://www.samcroremeras.com.ar/guia-de-talles/" target="_blank">No se mi talle, ver guia de medidas</a>
  <button class="btn-primary" id="btn-ver" onclick="verOpciones()" disabled>Ver opciones disponibles</button>
</div>

<div id="p2" class="paso">
  <button class="volver" onclick="irPaso(1)">volver</button>
  <p class="paso-titulo">Opciones en talle <span id="talle-elegido"></span></p>
  <p class="paso-sub">Toca la que mas te guste.</p>
  <div class="grid-remeras" id="grid-remeras"></div>
</div>

<div id="p3" class="paso">
  <button class="volver" onclick="irPaso(2)">volver</button>
  <p class="paso-titulo">Confirma tu eleccion</p>
  <p class="paso-sub" style="margin-bottom:1rem">Una vez confirmado te avisamos cuando llega.</p>
  <div class="timer" id="timer"></div>
  <div class="confirm-box"><label>Remera elegida</label><p id="conf-nombre"></p></div>
  <div class="confirm-box"><label>Talle</label><p id="conf-talle"></p></div>
  <div class="confirm-box"><label>Color</label><p id="conf-color"></p></div>
  <button class="btn-primary" onclick="confirmar()">Confirmar cambio</button>
</div>

<div id="p4" class="paso">
  <div class="success">
    <div class="success-icon">OK</div>
    <h2 style="font-size:1.1rem;margin-bottom:.5rem">Listo, recibimos tu eleccion</h2>
    <p style="font-size:.85rem;color:#666;line-height:1.6">Te vamos a escribir por WhatsApp para coordinar el envio. Gracias por tu paciencia.</p>
  </div>
</div>

<script>
var remeras = """ + remeras_json + """;
var tallesSel = '';
var remeraSel = null;
var timerInterval = null;
var TOKEN = '""" + str(token_id) + """';
window.onload = function() {
  var ts = {};
  remeras.forEach(function(r) { ts[r.talle] = true; });
  var talles = Object.keys(ts).sort();
  var g = document.getElementById('talles-grid');
  talles.forEach(function(t) {
    var b = document.createElement('button');
    b.className = 'talle-btn';
    b.textContent = t;
    b.onclick = function() {
      document.querySelectorAll('.talle-btn').forEach(function(x){ x.classList.remove('sel'); });
      b.classList.add('sel');
      tallesSel = t;
      document.getElementById('btn-ver').disabled = false;
    };
    g.appendChild(b);
  });
};

function irPaso(n) {
  document.querySelectorAll('.paso').forEach(function(p){ p.classList.remove('activo'); });
  document.getElementById('p' + n).classList.add('activo');
}

function verOpciones() {
  var filtradas = remeras.filter(function(r){ return r.talle === tallesSel; });
  var g = document.getElementById('grid-remeras');
  document.getElementById('talle-elegido').textContent = tallesSel;
  if (!filtradas.length) {
    g.innerHTML = '<p style="color:#666;font-size:.85rem;grid-column:1/-1">No hay opciones en este talle.</p>';
  } else {
    g.innerHTML = filtradas.map(function(r) {
      return '<div class="remera-card" onclick="selRemera(' + r.id + ', this)">' +
        '<img src="' + r.imagen_url + '" onerror="this.style.display=&quot;none&quot;" alt="">' +
        '<div class="info"><h3>' + r.nombre + '</h3><p>' + r.color + '</p></div></div>';
    }).join('');
  }
  irPaso(2);
}

function selRemera(id, el) {
  remeraSel = remeras.find(function(r){ return r.id === id; });
  document.querySelectorAll('.remera-card').forEach(function(c){ c.classList.remove('sel'); });
  el.classList.add('sel');
  document.getElementById('conf-nombre').textContent = remeraSel.nombre;
  document.getElementById('conf-talle').textContent = remeraSel.talle;
  document.getElementById('conf-color').textContent = remeraSel.color || '-';
  iniciarTimer();
  setTimeout(function(){ irPaso(3); }, 300);
}

function iniciarTimer() {
  var seg = 600;
  clearInterval(timerInterval);
  timerInterval = setInterval(function() {
    seg--;
    var m = Math.floor(seg / 60);
    var s = seg % 60;
    document.getElementById('timer').textContent = 'Esta seleccion se reserva por ' + m + ':' + (s < 10 ? '0' : '') + s + ' minutos';
    if (seg <= 0) { clearInterval(timerInterval); }
  }, 1000);
}

function confirmar() {
  if (!remeraSel) return;
  fetch('/api/confirmar-cambio', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({token: TOKEN, remera_id: remeraSel.id})
  }).then(function(r){ return r.json(); })
    .then(function(data){
      if (data.ok) { irPaso(4); }
      else { alert('Hubo un error, intenta de nuevo.'); }
    });
}
</script>
</body>
</html>"""
    return html
@app.post("/api/confirmar-cambio")
def confirmar_cambio(data: dict):
    token = data.get("token")
    remera_id = data.get("remera_id")
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM tokens_cambio WHERE token_id=%s;", (token,))
            t = cur.fetchone()
            if not t or t["usado"] or datetime.now() > t["expira_at"]:
                return {"ok": False}
            cur.execute("UPDATE tokens_cambio SET usado=TRUE, remera_elegida_id=%s WHERE token_id=%s;", (remera_id, token))
            cur.execute("UPDATE stock SET cantidad = cantidad - 1 WHERE id=%s;", (remera_id,))
            cur.execute("DELETE FROM stock WHERE id=%s AND cantidad <= 0;", (remera_id,))
            conn.commit()
    return {"ok": True}
    

@app.get("/api/buscar-productos")
def buscar_productos(q: str = ""):
    if not q or len(q) < 2:
        return []
    res = requests.get(
        f"https://api.tiendanube.com/v1/{TN_STORE_ID}/products",
        headers={
            "Authentication": f"bearer {TN_ACCESS_TOKEN}",
            "User-Agent": "Samcro Stock (samcroremeras@gmail.com)"
        },
        params={"q": q, "per_page": 10}
    )
    if res.status_code != 200:
        return []
    productos = res.json()
    resultado = []
    for p in productos:
        nombre = p.get("name", {}).get("es", "") or ""
        imagen = ""
        if p.get("images"):
            imagen = p["images"][0].get("src", "")
        link = p.get("canonical_url", "") or p.get("permalink", "")
        resultado.append({"nombre": nombre, "imagen": imagen, "link": link})
    return resultado

@app.post("/api/actualizar-imagenes")
def actualizar_imagenes():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nombre FROM stock WHERE imagen_url IS NULL OR imagen_url = '';")
            remeras = cur.fetchall()
    
    actualizadas = 0
    for r in remeras:
        try:
            res = requests.get(
                f"https://api.tiendanube.com/v1/{TN_STORE_ID}/products",
                headers={
                    "Authentication": f"bearer {TN_ACCESS_TOKEN}",
                    "User-Agent": "Samcro Stock (samcroremeras@gmail.com)"
                },
                params={"q": r["nombre"], "per_page": 10, "category_id": 1031807}
            )
            if res.status_code != 200:
                continue
            productos = res.json()
            if not productos:
                continue
            imagen = ""
            link = ""
            for p in productos:
                nombre_tn = p.get("name", {}).get("es", "") or ""
                if nombre_tn.lower().strip() == r["nombre"].lower().strip():
                    if p.get("images"):
                        imagen = p["images"][0].get("src", "")
                    link = p.get("canonical_url", "") or p.get("permalink", "")
                    break
            if imagen or link:
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE stock SET imagen_url=%s, link_tienda=%s WHERE id=%s;",
                            (imagen, link, r["id"])
                        )
                        conn.commit()
                actualizadas += 1
        except:
            continue
    
    return {"ok": True, "actualizadas": actualizadas}
    
@app.get("/api/categorias")
def get_categorias():
    res = requests.get(
        f"https://api.tiendanube.com/v1/{TN_STORE_ID}/categories",
        headers={
            "Authentication": f"bearer {TN_ACCESS_TOKEN}",
            "User-Agent": "Samcro Stock (samcroremeras@gmail.com)"
        }
    )
    return res.json()
    
PANEL_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Samcro - Panel de Stock</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#f5f5f5;color:#111}
header{background:#111;color:#fff;padding:1rem 2rem;display:flex;justify-content:space-between;align-items:center}
header h1{font-size:1.1rem;font-weight:600;letter-spacing:.05em}
.actions{display:flex;gap:.5rem}
.btn{padding:.5rem 1rem;border-radius:6px;border:none;cursor:pointer;font-size:.85rem;font-weight:500}
.btn-white{background:#fff;color:#111}
.btn-green{background:#16a34a;color:#fff}
.btn-blue{background:#2563eb;color:#fff}
main{padding:1.5rem 2rem}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem;margin-bottom:1.5rem}
.stat{background:#fff;border-radius:8px;padding:1rem;border:1px solid #e5e5e5}
.stat p{font-size:.75rem;color:#666;margin-bottom:.25rem}
.stat h2{font-size:1.5rem;font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:1rem}
.card{background:#fff;border-radius:8px;border:1px solid #e5e5e5;overflow:hidden}
.card img{width:100%;height:180px;object-fit:cover;background:#f0f0f0}
.card-body{padding:.75rem}
.card-body h3{font-size:.9rem;font-weight:600;margin-bottom:.25rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card-body p{font-size:.8rem;color:#666}
.badges{display:flex;gap:.25rem;margin:.4rem 0;flex-wrap:wrap}
.badge{font-size:.7rem;padding:.15rem .5rem;border-radius:20px;font-weight:500}
.bt{background:#e0f2fe;color:#0369a1}
.bc{background:#f0fdf4;color:#15803d}
.bs{background:#fef9c3;color:#854d0e}
.card-actions{display:flex;gap:.25rem;margin-top:.5rem}
.card-actions button{flex:1;padding:.35rem;border-radius:4px;border:none;cursor:pointer;font-size:.75rem}
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:100;align-items:center;justify-content:center}
.modal-bg.open{display:flex}
.modal{background:#fff;border-radius:12px;padding:1.5rem;width:100%;max-width:420px;max-height:90vh;overflow-y:auto}
.modal h2{font-size:1rem;font-weight:600;margin-bottom:1rem}
.field{margin-bottom:.75rem}
.field label{display:block;font-size:.8rem;color:#666;margin-bottom:.25rem}
.field input,.field select{width:100%;padding:.5rem;border:1px solid #ddd;border-radius:6px;font-size:.85rem}
.field-row{display:grid;grid-template-columns:1fr 1fr;gap:.5rem}
.modal-actions{display:flex;justify-content:flex-end;gap:.5rem;margin-top:1rem}
.empty{text-align:center;padding:3rem;color:#999;grid-column:1/-1}
.sg-item{display:flex;align-items:center;gap:8px;padding:8px;cursor:pointer;border-bottom:1px solid #f0f0f0}
.sg-item:hover{background:#f9f9f9}
.token-box{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:1rem;margin-top:1rem}
.token-box p{font-size:.8rem;color:#15803d;margin-bottom:.5rem}
.token-box a{color:#15803d;font-weight:600;word-break:break-all}
</style>
</head>
<body>
<header>
  <h1>SAMCRO - Stock</h1>
  <div class="actions">
    <button class="btn btn-white" onclick="abrirModal()">+ Nueva remera</button>
    <button class="btn btn-blue" onclick="document.getElementById('fi').click()">Importar Excel</button>
    <button class="btn btn-green" onclick="exportar()">Exportar Excel</button>
    <button class="btn" style="background:#7c3aed;color:#fff" onclick="actualizarImagenes()">Actualizar imagenes</button>
    <input type="file" id="fi" accept=".xlsx" style="display:none" onchange="importar(this)">
  </div>
</header>
<main>
  <div class="stats">
    <div class="stat"><p>Total remeras</p><h2 id="st">-</h2></div>
    <div class="stat"><p>Unidades en stock</p><h2 id="su">-</h2></div>
    <div class="stat"><p>Sin stock</p><h2 id="ss">-</h2></div>
  </div>
  <div class="grid" id="grid"><p class="empty">Cargando...</p></div>
</main>

<div class="modal-bg" id="modal">
  <div class="modal">
    <h2 id="mt">Nueva remera</h2>
    <input type="hidden" id="eid">
    <div class="field">
      <label>Nombre</label>
      <input id="fn" placeholder="Escribi para buscar..." autocomplete="off" oninput="buscar(this.value)">
      <div id="sg" style="border:1px solid #ddd;border-radius:6px;margin-top:4px;display:none;max-height:200px;overflow-y:auto;background:#fff"></div>
    </div>
    <div class="field-row">
      <div class="field"><label>Categoria</label>
        <select id="fcat">
          <option>Musica</option><option>Cine y Series</option>
          <option>Superheroes</option><option>Videojuegos</option>
          <option>Autos y Motos</option><option>Otros</option>
        </select>
      </div>
      <div class="field"><label>Talle</label>
        <select id="ft">
  <option>XS</option><option>S</option><option>M</option>
  <option>L</option><option>XL</option><option>XXL</option>
  <option>XXXL</option><option>4XL</option><option>5XL</option>
  <option>6XL</option><option>7XL</option>
</select>
      </div>
    </div>
    <div class="field-row">
      <div class="field"><label>Color</label><input id="fc" placeholder="negra"></div>
      <div class="field"><label>Cantidad</label><input id="fq" type="number" min="0" value="1"></div>
    </div>
    <div class="field"><label>URL imagen</label><input id="fi2" placeholder="https://..."></div>
    <div class="field"><label>Link tienda</label><input id="fl" placeholder="https://samcroremeras.com.ar/..."></div>
    <div class="modal-actions">
      <button class="btn" onclick="cerrar()">Cancelar</button>
      <button class="btn btn-green" onclick="guardar()">Guardar</button>
    </div>
  </div>
</div>

<div class="modal-bg" id="mtoken">
  <div class="modal">
    <h2>Generar link de cambio</h2>
    <div class="field"><label>Numero de orden</label><input id="torden" placeholder="10042"></div>
    <div class="modal-actions">
      <button class="btn" onclick="document.getElementById('mtoken').classList.remove('open')">Cancelar</button>
      <button class="btn btn-green" onclick="genToken()">Generar link</button>
    </div>
    <div class="token-box" id="tresult" style="display:none">
      <p>Link generado (expira en 24hs):</p>
      <a id="tlink" href="#" target="_blank"></a>
    </div>
  </div>
</div>

<script>
var remeras = [];
var sugs = [];

function esc(s) {
  return (s === null || s === undefined) ? '' : String(s).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function buscar(q) {
  var box = document.getElementById('sg');
  if (q.length < 2) { box.style.display = 'none'; return; }
  fetch('/api/buscar-productos?q=' + encodeURIComponent(q))
    .then(function(r){ return r.json(); })
    .then(function(items){
      sugs = items;
      if (!items.length) { box.style.display = 'none'; return; }
      box.style.display = 'block';
      var html = '';
      for (var i = 0; i < items.length; i++) {
        html += '<div class="sg-item" onclick="elegir(' + i + ')">';
       html += '<img src="' + esc(items[i].imagen) + '" style="width:40px;height:40px;object-fit:cover;border-radius:4px" onerror="this.style.display=&quot;none&quot;">';
        html += '<span style="font-size:.85rem">' + esc(items[i].nombre) + '</span>';
        html += '</div>';
      }
      box.innerHTML = html;
    });
}

function elegir(i) {
  var p = sugs[i];
  document.getElementById('fn').value = p.nombre;
  document.getElementById('fi2').value = p.imagen;
  document.getElementById('fl').value = p.link;
  document.getElementById('sg').style.display = 'none';
}

function cargar() {
  fetch('/api/stock')
    .then(function(r){ return r.json(); })
    .then(function(data){
      remeras = data;
      renderizar();
    });
}

function renderizar() {
  var grid = document.getElementById('grid');
  var total = remeras.length;
  var unidades = 0;
  var sin = 0;
  for (var i = 0; i < remeras.length; i++) {
    unidades += remeras[i].cantidad || 0;
    if (!remeras[i].cantidad) sin++;
  }
  document.getElementById('st').textContent = total;
  document.getElementById('su').textContent = unidades;
  document.getElementById('ss').textContent = sin;
  if (!total) { grid.innerHTML = '<p class="empty">No hay remeras en stock.</p>'; return; }
  var html = '';
  for (var i = 0; i < remeras.length; i++) {
    var r = remeras[i];
    html += '<div class="card">';
    html += '<img src="' + esc(r.imagen_url) + '" onerror="this.style.display=&quot;none&quot;" alt="">';
    html += '<div class="card-body">';
    html += '<h3 title="' + esc(r.nombre) + '">' + esc(r.nombre) + '</h3>';
    html += '<div class="badges">';
    html += '<span class="badge bt">' + esc(r.talle) + '</span>';
    html += '<span class="badge bc">' + esc(r.categoria) + '</span>';
    html += '<span class="badge bs">x' + (r.cantidad || 0) + '</span>';
    html += '</div>';
    html += '<p>' + esc(r.color) + '</p>';
    html += '<div class="card-actions">';
    html += '<button style="color:#fff;background:#2563eb" onclick="editar(' + r.id + ')">Editar</button>';
    html += '<button style="background:#fee2e2;color:#dc2626" onclick="eliminar(' + r.id + ')">Eliminar</button>';
    html += '<button style="background:#f0fdf4;color:#16a34a" onclick="abrirToken(' + r.id + ')">Link cambio</button>';
    html += '</div></div></div>';
  }
  grid.innerHTML = html;
}

function abrirModal() {
  document.getElementById('mt').textContent = 'Nueva remera';
  document.getElementById('eid').value = '';
  document.getElementById('fn').value = '';
  document.getElementById('fc').value = '';
  document.getElementById('fi2').value = '';
  document.getElementById('fl').value = '';
  document.getElementById('fq').value = 1;
  document.getElementById('sg').style.display = 'none';
  document.getElementById('modal').classList.add('open');
}

function cerrar() { document.getElementById('modal').classList.remove('open'); }

function editar(id) {
  var r = null;
  for (var i = 0; i < remeras.length; i++) { if (remeras[i].id === id) { r = remeras[i]; break; } }
  if (!r) return;
  document.getElementById('mt').textContent = 'Editar remera';
  document.getElementById('eid').value = id;
  document.getElementById('fn').value = r.nombre || '';
  document.getElementById('fcat').value = r.categoria || 'Musica';
  document.getElementById('ft').value = r.talle || 'M';
  document.getElementById('fc').value = r.color || '';
  document.getElementById('fq').value = r.cantidad || 0;
  document.getElementById('fi2').value = r.imagen_url || '';
  document.getElementById('fl').value = r.link_tienda || '';
  document.getElementById('modal').classList.add('open');
}

function guardar() {
  var id = document.getElementById('eid').value;
  var data = {
    nombre: document.getElementById('fn').value,
    categoria: document.getElementById('fcat').value,
    talle: document.getElementById('ft').value,
    color: document.getElementById('fc').value,
    cantidad: parseInt(document.getElementById('fq').value) || 0,
    imagen_url: document.getElementById('fi2').value,
    link_tienda: document.getElementById('fl').value
  };
  var url = id ? '/api/stock/' + id : '/api/stock';
  var method = id ? 'PUT' : 'POST';
  fetch(url, {method: method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)})
    .then(function(){ cerrar(); cargar(); });
}

function eliminar(id) {
  if (!confirm('Eliminar esta remera?')) return;
  fetch('/api/stock/' + id, {method: 'DELETE'}).then(function(){ cargar(); });
}

function importar(input) {
  var fd = new FormData();
  fd.append('file', input.files[0]);
  fetch('/api/importar-excel', {method: 'POST', body: fd})
    .then(function(r){ return r.json(); })
    .then(function(data){ alert('Importadas: ' + data.importadas + ' remeras'); input.value = ''; cargar(); });
}

function exportar() { window.location.href = '/api/exportar-excel'; }

function abrirToken(id) {
  document.getElementById('torden').value = '';
  document.getElementById('tresult').style.display = 'none';
  document.getElementById('mtoken').classList.add('open');
}

function genToken() {
  var orden = document.getElementById('torden').value;
  if (!orden) { alert('Ingresa el numero de orden'); return; }
  fetch('/api/tokens?orden_nro=' + orden, {method: 'POST'})
    .then(function(r){ return r.json(); })
    .then(function(data){
      document.getElementById('tlink').textContent = data.link;
      document.getElementById('tlink').href = data.link;
      document.getElementById('tresult').style.display = 'block';
    });
}

function actualizarImagenes() {
  if (!confirm('Esto puede tardar 1-2 minutos. Continuar?')) return;
  fetch('/api/actualizar-imagenes', {method: 'POST'})
    .then(function(r){ return r.json(); })
    .then(function(data){ alert('Actualizadas: ' + data.actualizadas + ' remeras'); cargar(); });
}
cargar();
</script>
</body>
</html>"""

@app.get("/panel", response_class=HTMLResponse)
def panel():
    return PANEL_HTML
