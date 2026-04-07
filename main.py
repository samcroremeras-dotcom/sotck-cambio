from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
import io
import requests

app = FastAPI()
DATABASE_URL = os.getenv("DATABASE_URL")
TN_CLIENT_ID = os.getenv("TN_CLIENT_ID")
TN_CLIENT_SECRET = os.getenv("TN_CLIENT_SECRET")

class Remera(BaseModel):
    nombre: str
    talle: str
    color: str = ""
    cantidad: int = 0
    imagen_url: str = ""
    link_tienda: str = ""

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# --- RUTAS DE LA API ---

@app.get("/api/stock")
def obtener_stock():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM stock ORDER BY id DESC;")
    remeras = cur.fetchall()
    cur.close()
    conn.close()
    return remeras

@app.get("/api/nombres-productos")
def obtener_nombres():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT nombre FROM stock ORDER BY nombre ASC;")
    nombres = [row['nombre'] for row in cur.fetchall()]
    cur.close()
    conn.close()
    return nombres

@app.post("/api/stock")
def agregar_remera(remera: Remera):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO stock (nombre, talle, color, cantidad, imagen_url, link_tienda)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id;
    """, (remera.nombre, remera.talle, remera.color, remera.cantidad, remera.imagen_url, remera.link_tienda))
    nuevo_id = cur.fetchone()['id']
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success", "id": nuevo_id}

@app.post("/api/importar-excel")
async def importar_excel(file: UploadFile = File(...)):
    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        contador = 0
        for index, row in df.iterrows():
            cur.execute("""
                INSERT INTO stock (nombre, talle, color, cantidad, imagen_url, link_tienda)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                str(row.get('nombre', '')),
                str(row.get('talle', '')),
                str(row.get('color', '')),
                int(row.get('cantidad', 0) if pd.notna(row.get('cantidad')) else 0),
                str(row.get('imagen_url', '')),
                str(row.get('link_tienda', ''))
            ))
            contador += 1
            
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "success", "mensaje": f"{contador} remeras importadas correctamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- RUTA PARA CONECTAR TIENDANUBE ---

@app.get("/auth/callback")
def auth_callback(code: str):
    url = "https://www.tiendanube.com/apps/authorize/token"
    data = {
        "client_id": TN_CLIENT_ID,
        "client_secret": TN_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code
    }
    headers = {
        "User-Agent": "Samcro Stock API (samcroremeras@gmail.com)"
    }
    
    response = requests.post(url, data=data, headers=headers)
    
    if response.status_code == 200:
        auth_data = response.json()
        return {
            "mensaje": "¡EXITO! Conexion con Tiendanube lograda.",
            "instruccion": "Copia estos 2 valores y agregalos en la pestaña Variables de Railway:",
            "TN_ACCESS_TOKEN": auth_data.get("access_token"),
            "TN_STORE_ID": auth_data.get("user_id")
        }
    else:
        return {"error": "Fallo la conexion", "detalle": response.text}

# --- INTERFAZ VISUAL (DASHBOARD) ---

@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Samcro - Panel de Stock</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-100 font-sans">
        <div class="max-w-6xl mx-auto p-6">
            <header class="flex justify-between items-center mb-8">
                <h1 class="text-3xl font-bold text-gray-800">Samcro Stock</h1>
                <div class="space-x-2">
                    <input type="file" id="excel-file" accept=".xlsx, .xls" class="hidden" onchange="subirExcel(this)">
                    <button onclick="document.getElementById('excel-file').click()" class="bg-blue-600 text-white px-4 py-2 rounded-full hover:bg-blue-700 transition shadow">
                        📄 Importar Excel
                    </button>
                    <button onclick="abrirModal()" class="bg-black text-white px-6 py-2 rounded-full hover:bg-gray-800 transition shadow">
                        + Nueva
                    </button>
                </div>
            </header>

            <div id="loading" class="hidden text-center text-blue-600 font-bold mb-4">Cargando Excel... por favor espera.</div>

            <div id="stock-grid" class="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-6"></div>
        </div>

        <div id="modal" class="hidden fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4">
            <div class="bg-white rounded-xl p-8 max-w-md w-full shadow-2xl">
                <h2 class="text-2xl font-bold mb-4">Cargar Nueva Remera</h2>
                <form id="remera-form" class="space-y-4">
                    
                    <div>
                        <input type="text" id="nombre" list="lista-nombres" placeholder="Buscar o escribir nombre del diseño..." class="w-full border p-2 rounded" required autocomplete="off">
                        <datalist id="lista-nombres"></datalist>
                    </div>

                    <div class="grid grid-cols-2 gap-4">
                        <select id="talle" class="border p-2 rounded">
                            <option>S</option><option>M</option><option>L</option><option>XL</option><option>XXL</option>
                        </select>
                        <input type="text" id="color" placeholder="Color" class="border p-2 rounded">
                    </div>
                    <input type="number" id="cantidad" placeholder="Cantidad" class="w-full border p-2 rounded" required>
                    <input type="url" id="imagen_url" placeholder="URL de la imagen" class="w-full border p-2 rounded">
                    <input type="url" id="link_tienda" placeholder="Link a la tienda" class="w-full border p-2 rounded">
                    <div class="flex justify-end space-x-2 pt-4">
                        <button type="button" onclick="document.getElementById('modal').classList.add('hidden')" class="text-gray-500 px-4 py-2">Cancelar</button>
                        <button type="submit" class="bg-green-600 text-white px-6 py-2 rounded hover:bg-green-700">Guardar</button>
                    </div>
                </form>
            </div>
        </div>

        <script>
            async function cargarNombres() {
                const res = await fetch('/api/nombres-productos');
                const nombres = await res.json();
                const datalist = document.getElementById('lista-nombres');
                datalist.innerHTML = '';
                nombres.forEach(nombre => {
                    datalist.innerHTML += `<option value="${nombre}">`;
                });
            }

            function abrirModal() {
                cargarNombres(); // Carga los nombres actualizados cada vez que abrís el modal
                document.getElementById('modal').classList.remove('hidden');
