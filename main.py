import os, io, uuid
from datetime import datetime, timedelta
import pandas as pd
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import create_engine, text

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Configuración de Base de Datos
DATABASE_URL = os.getenv("DATABASE_URL").replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL)

# TOKEN DE TIENDANUBE (Lo dejamos guardado para usarlo después)
TN_TOKEN = "5692f19ea10d5eed1043983dbf28a48ea9ac1bb5"

@app.get("/", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})

@app.post("/upload-csv")
async def upload_csv(file: UploadFile = File(...)):
    content = await file.read()
    # Leemos el CSV con la estructura de tus archivos
    df = pd.read_csv(io.StringIO(content.decode('utf-8')))
    
    # Mapeamos tus columnas a la base de datos
    df.columns = ['nombre', 'color', 'talle', 'cantidad', 'link_tienda']
    
    # Guardamos en la tabla 'stock' (append para ir sumando todos los talles)
    df.to_sql('stock', engine, if_exists='append', index=False)
    
    return RedirectResponse(url="/?status=success", status_code=303)

@app.post("/generar-link")
async def generar_link(orden: str = Form(...), talle_cambio: str = Form(...)):
    # Creamos un código único para el cliente
    token = str(uuid.uuid4())[:8]
    expira = datetime.now() + timedelta(hours=24)
    
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO tokens_cambio (token_id, orden_nro, talle_sugerido, expira_at) VALUES (:t, :o, :ts, :e)"),
            {"t": token, "o": orden, "ts": talle_cambio, "e": expira}
        )
        conn.commit()
    
    # URL que le vas a pasar por WhatsApp (usamos el dominio de Railway)
    link = f"https://{os.getenv('RAILWAY_STATIC_URL')}/cambio/{token}"
    return {"mensaje": f"Link generado para la orden {orden}", "url": link}
