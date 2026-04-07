
import os
from fastapi import FastAPI
from sqlalchemy import create_engine, text

app = FastAPI()

# Buscamos la URL de la base de datos que cargamos en Railway
DATABASE_URL = os.getenv("DATABASE_URL")

# Pequeño truco técnico: Railway a veces da la URL como 'postgres://', 
# pero Python necesita que diga 'postgresql://'
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)

# --- ESTO SE EJECUTA APENAS SE PRENDE LA APP ---
@app.on_event("startup")
def init_db():
    with engine.connect() as conn:
        # Creamos la tabla 'stock' si no existe
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS stock (
                id SERIAL PRIMARY KEY,
                nombre TEXT,
                talle TEXT,
                color TEXT,
                cantidad INTEGER,
                imagen_url TEXT,
                link_tienda TEXT
            );
        """))
        conn.commit()

@app.get("/")
def read_root():
    return {
        "status": "ok", 
        "servicio": "Samcro Stock API", 
        "db_status": "Conectada y tablas creadas"
    }
