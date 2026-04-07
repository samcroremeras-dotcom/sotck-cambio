import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import create_engine, text
import pandas as pd

app = FastAPI()

# Leemos la URL que configuraste en Railway
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

# --- ESTO CREA LAS TABLAS AUTOMÁTICAMENTE ---
def init_db():
    with engine.connect() as conn:
        # Tabla de Stock
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stock_remeras (
                id SERIAL PRIMARY KEY,
                nombre TEXT,
                talle TEXT,
                color TEXT,
                cantidad INTEGER,
                imagen_url TEXT,
                link_tienda TEXT
            );
        """))
        # Tabla de Links (Tokens)
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tokens_cambio (
                token_id TEXT PRIMARY KEY,
                orden_nro TEXT,
                talle_sugerido TEXT,
                expira_at TIMESTAMP,
                usado BOOLEAN DEFAULT FALSE
            );
        """))
        conn.commit()

# Ejecutamos la creación de tablas al arrancar
init_db()

@app.get("/", response_class=HTMLResponse)
async def home():
    return """
    <html>
        <body style="background-color: #000; color: #fff; font-family: sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh;">
            <h1 style="color: #e31b23;">SAMCRO STOCK SYSTEM</h1>
            <p>Estado: 🟢 Conectado a la Base de Datos</p>
            <p style="font-size: 0.8em; color: #666;">Paso 3 completado. Esperando el panel de control...</p>
        </body>
    </html>
    """
