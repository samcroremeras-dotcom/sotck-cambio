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
    
    # LA MAGIA ESTÁ ACÁ: cambiamos data
