import os
from fastapi import FastAPI
from sqlalchemy import create_engine, text

app = FastAPI()

# 1. Leemos la URL de la base de datos desde Railway
DATABASE_URL = os.getenv("DATABASE_URL")

# Truco para que Python acepte la URL de Railway
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 2. Creamos la conexión
engine = create_engine(DATABASE_URL)

# 3. Función que crea las tablas apenas arranca la App
@app.on_event("startup")
def init_db():
    with engine.connect() as conn:
        # Tabla para guardar todas tus remeras de los Excel
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stock (
                id SERIAL PRIMARY KEY,
                nombre TEXT,
                color TEXT,
                talle TEXT,
                cantidad INTEGER,
                link_tienda TEXT
            );
        """))
        # Tabla para los links de 24hs
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

@app.get("/")
def check_status():
    return {
        "status": "ok",
        "servicio": "Samcro Stock API",
        "db_status": "Conectada y tablas creadas"
    }
