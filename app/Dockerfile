# Imagen de producción para "Mi patrimonio"
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PATRIMONIO_DATA_DIR=/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# /data debe ser un volumen persistente (snapshots + histórico de precios).
VOLUME ["/data"]
EXPOSE 8000

# Forma shell para expandir $PORT (Render/host asigna el puerto; 8000 por defecto).
# Un solo worker: comparte el scheduler en proceso y la caché de precios.
CMD gunicorn app:app --workers 1 --threads 4 --bind 0.0.0.0:${PORT:-8000} --timeout 180
