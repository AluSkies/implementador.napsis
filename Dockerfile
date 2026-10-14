FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Las dependencias primero: mientras requirements.txt no cambie, esta capa se
# reusa y un release de código solo reconstruye lo de abajo.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# - El entrypoint puede llegar con fin de línea CRLF si se construye desde Windows.
# - collectstatic en el build: los estáticos quedan dentro de la imagen y los sirve
#   WhiteNoise (no hace falta compartir nada con el proxy). La SECRET_KEY de acá
#   es solo para que Django arranque durante el build; la real viene por entorno.
# - El usuario necesita un home escribible: Gunicorn guarda ahí su socket de control.
# - media/ es el volumen donde la app guarda los adjuntos subidos.
RUN sed -i 's/\r$//' docker/entrypoint.sh \
    && chmod +x docker/entrypoint.sh \
    && DJANGO_SECRET_KEY=solo-para-el-build python manage.py collectstatic --no-input \
    && useradd --system --create-home --home-dir /home/napsis napsis \
    && mkdir -p /app/media \
    && chown -R napsis:napsis /app/media

USER napsis
EXPOSE 8000

ENTRYPOINT ["docker/entrypoint.sh"]
# Mismo tuning que el paquete systemd de deploy/: pocos workers, bajo consumo de RAM.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "2", "--threads", "2", "--worker-tmp-dir", "/dev/shm", \
     "--max-requests", "500", "--max-requests-jitter", "50"]
