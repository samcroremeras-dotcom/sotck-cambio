from fastapi import FastAPI
import os
import psycopg2 # Asegúrate de tener 'psycopg2-binary' en tu requirements.txt

app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")

@app.get("/")
def home():
    db_status = "No conectada"
    try:
        # Intentamos conectar a la base de datos
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        # Paso 2.2: Crear las tablas automáticamente si no existen
        cur.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                id SERIAL PRIMARY KEY,
                nombre TEXT NOT NULL,
                talle TEXT NOT NULL,
                color TEXT,
                cantidad INTEGER DEFAULT 0,
                imagen_url TEXT,
                link_tienda TEXT,
                creado_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        db_status = "Conectada y tablas creadas"
    except Exception as e:
        db_status = f"Error: {str(e)}"

    return {
        "status": "ok",
        "servicio": "Samcro Stock API",
        "db_status": db_status
    }
