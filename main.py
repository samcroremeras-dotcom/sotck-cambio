from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI()
DATABASE_URL = os.getenv("DATABASE_URL")

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
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css">
    </head>
    <body class="bg-gray-100 font-sans">
        <div class="max-w-6xl mx-auto p-6">
            <header class="flex justify-between items-center mb-8">
                <h1 class="text-3xl font-bold text-gray-800">Samcro Stock</h1>
                <button onclick="document.getElementById('modal').classList.remove('hidden')" class="bg-black text-white px-6 py-2 rounded-full hover:bg-gray-800 transition">
                    + Nueva Remera
                </button>
            </header>

            <div id="stock-grid" class="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-6">
                </div>
        </div>

        <div id="modal" class="hidden fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4">
            <div class="bg-white rounded-xl p-8 max-w-md w-full shadow-2xl">
                <h2 class="text-2xl font-bold mb-4">Cargar Nueva Remera</h2>
                <form id="remera-form" class="space-y-4">
                    <input type="text" id="nombre" placeholder="Nombre del diseño" class="w-full border p-2 rounded" required>
                    <div class="grid grid-cols-2 gap-4">
                        <select id="talle" class="border p-2 rounded">
                            <option>S</option><option>M</option><option>L</option><option>XL</option><option>XXL</option>
                        </select>
                        <input type="text" id="color" placeholder="Color" class="border p-2 rounded">
                    </div>
                    <input type="number" id="cantidad" placeholder="Cantidad" class="w-full border p-2 rounded" required>
                    <input type="url" id="imagen_url" placeholder="URL de la imagen (link directo)" class="w-full border p-2 rounded" required>
                    <input type="url" id="link_tienda" placeholder="Link a la tienda" class="w-full border p-2 rounded">
                    <div class="flex justify-end space-x-2 pt-4">
                        <button type="button" onclick="document.getElementById('modal').classList.add('hidden')" class="text-gray-500 px-4 py-2">Cancelar</button>
                        <button type="submit" class="bg-green-600 text-white px-6 py-2 rounded hover:bg-green-700">Guardar</button>
                    </div>
                </form>
            </div>
        </div>

        <script>
            async function cargarStock() {
                const res = await fetch('/api/stock');
                const data = await res.json();
                const grid = document.getElementById('stock-grid');
                grid.innerHTML = '';
                
                data.forEach(item => {
                    grid.innerHTML += `
                        <div class="bg-white rounded-lg shadow overflow-hidden border border-gray-200 transition hover:shadow-lg">
                            <img src="${item.imagen_url}" class="w-full h-48 object-cover bg-gray-200" onerror="this.src='https://via.placeholder.com/200?text=Sin+Imagen'">
                            <div class="p-4">
                                <h3 class="font-bold text-lg text-gray-800 truncate">${item.nombre}</h3>
                                <div class="flex justify-between items-center mt-2">
                                    <span class="bg-gray-100 px-2 py-1 rounded text-sm font-semibold">Talle: ${item.talle}</span>
                                    <span class="text-green-600 font-bold">Cant: ${item.cantidad}</span>
                                </div>
                                <a href="${item.link_tienda}" target="_blank" class="block text-center mt-4 text-blue-500 text-sm underline">Ver en tienda</a>
                            </div>
                        </div>
                    `;
                });
            }

            document.getElementById('remera-form').onsubmit = async (e) => {
                e.preventDefault();
                const remera = {
                    nombre: document.getElementById('nombre').value,
                    talle: document.getElementById('talle').value,
                    color: document.getElementById('color').value,
                    cantidad: parseInt(document.getElementById('cantidad').value),
                    imagen_url: document.getElementById('imagen_url').value,
                    link_tienda: document.getElementById('link_tienda').value
                };

                const res = await fetch('/api/stock', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(remera)
                });

                if (res.ok) {
                    document.getElementById('modal').classList.add('hidden');
                    document.getElementById('remera-form').reset();
                    cargarStock();
                }
            };

            cargarStock();
        </script>
    </body>
    </html>
    """
