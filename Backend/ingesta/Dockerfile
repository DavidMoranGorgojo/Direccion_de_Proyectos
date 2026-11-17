# Servicio backend-ingesta (diseño «Arquitectura del backend y dockerización», §7.2).
# El modelo bge-m3 (~2,3 GB) se descarga la primera vez en el volumen /cache/huggingface.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/cache/huggingface \
    INGESTA_ENTRADA=/data/manuales \
    INGESTA_SALIDA=/data/salida
VOLUME ["/cache/huggingface"]

ENTRYPOINT ["python", "-m", "ingesta"]
CMD ["--cargar"]
