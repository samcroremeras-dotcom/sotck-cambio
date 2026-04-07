from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import psycopg2
from psycopg2.extras import RealDictCursor

app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")

# Modelo de datos para la remera
class Remera(BaseModel):
    nombre: str
    talle: str
    color: str = ""
    cantidad: int = 0
    imagen_url: str = ""
    link_tienda: str = ""

# Función para conectar a la base de datos
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

@app.get("/")
def home():
    return {"status": "ok", "servicio": "Samcro Stock API", "db_status": "Conectada y lista"}

# Ruta para VER todo el stock
@app.get("/api/stock")
def obtener_stock():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM stock ORDER BY id DESC;")
        remeras = cur.fetchall()
        cur.close()
        conn.close()
        return remeras
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Ruta para GUARDAR una remera nueva
@app.post("/api/stock")
def agregar_remera(remera: Remera):
    try:
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
        return {"mensaje": "Remera agregada con éxito", "id": nuevo_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
