import os
import io
import uuid
import requests
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
    return f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Elegi tu cambio</title></head>
<body><h1>Orden #{t["orden_nro"]}</h1><p>Pagina del cliente - proximamente.</p></body>
</html>"""

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
        link = p.get("permalink", "")
        resultado.append({"nombre": nombre, "imagen": imagen, "link": link})
    return resultado

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
          <option>L</option><option>XL</option><option>XXL</option><option>XXXL</option>
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
        html += '<img src="' + items[i].imagen + '" style="width:40px;height:40px;object-fit:cover;border-radius:4px" onerror="this.style.display=\'none\'">';
        html += '<span style="font-size:.85rem">' + items[i].nombre + '</span>';
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
    if (remeras[i].cantidad === 0) sin++;
  }
  document.getElementById('st').textContent = total;
  document.getElementById('su').textContent = unidades;
  document.getElementById('ss').textContent = sin;
  if (!total) { grid.innerHTML = '<p class="empty">No hay remeras en stock.</p>'; return; }
  var html = '';
  for (var i = 0; i < remeras.length; i++) {
    var r = remeras[i];
    html += '<div class="card">';
    html += '<img src="' + (r.imagen_url || '') + '" onerror="this.style.display=\'none\'" alt="">';
    html += '<div class="card-body">';
    html += '<h3 title="' + r.nombre + '">' + r.nombre + '</h3>';
    html += '<div class="badges">';
    html += '<span class="badge bt">' + r.talle + '</span>';
    html += '<span class="badge bc">' + (r.categoria || '') + '</span>';
    html += '<span class="badge bs">x' + r.cantidad + '</span>';
    html += '</div>';
    html += '<p>' + (r.color || '') + '</p>';
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

cargar();
</script>
</body>
</html>"""

@app.get("/panel", response_class=HTMLResponse)
def panel():
    return PANEL_HTML
