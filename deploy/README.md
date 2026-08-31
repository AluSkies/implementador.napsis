# Deploy en Ubuntu Server (bare metal, sin Docker)

Pensado para correr en una máquina que ya tiene otras cosas (ej. un server
de juego): pocos workers, MySQL tuneado a la baja, todo con `systemd` así
sobrevive a reinicios sin depender de una sesión de terminal abierta.

## 1. Paquetes del sistema

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip mysql-server nginx git
```

(`PyMySQL` se usa en vez de `mysqlclient`, así que no hace falta
`libmysqlclient-dev` ni `build-essential`.)

## 2. Base de datos

```bash
# Editá la password en el archivo antes de correrlo
sudo mysql < deploy/setup_mysql.sql

# Tuning para bajo consumo de RAM
sudo cp deploy/mysql-napsis-tuning.cnf /etc/mysql/mysql.conf.d/
sudo systemctl restart mysql
```

## 3. Usuario del sistema y código

```bash
sudo useradd --system --home /opt/napsis-portal --shell /usr/sbin/nologin napsis
sudo mkdir -p /opt/napsis-portal
sudo chown napsis:napsis /opt/napsis-portal

sudo -u napsis git clone <URL-DE-TU-REPO> /opt/napsis-portal
cd /opt/napsis-portal

sudo -u napsis python3 -m venv venv
sudo -u napsis venv/bin/pip install -r requirements.txt
```

## 4. Configuración

```bash
sudo -u napsis cp deploy/.env.production.example .env
sudo -u napsis nano .env   # completar secret key, password de MySQL, host/IP real
```

Generar una `DJANGO_SECRET_KEY` nueva:

```bash
venv/bin/python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## 5. Migrar, estáticos y superusuario

```bash
sudo -u napsis venv/bin/python manage.py migrate
sudo -u napsis venv/bin/python manage.py seed_catalogos
sudo -u napsis venv/bin/python manage.py seed_modulos
sudo -u napsis venv/bin/python manage.py collectstatic --no-input
sudo -u napsis venv/bin/python manage.py createsuperuser
```

## 6. Servicio (gunicorn vía systemd)

```bash
sudo cp deploy/napsis-portal.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now napsis-portal
sudo systemctl status napsis-portal   # debería decir "active (running)"
```

## 7. Nginx

```bash
sudo cp deploy/nginx-napsis-portal.conf /etc/nginx/sites-available/napsis-portal
# Editá server_name con el hostname o IP de la máquina
sudo nano /etc/nginx/sites-available/napsis-portal

sudo ln -s /etc/nginx/sites-available/napsis-portal /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Con eso ya debería responder en `http://<ip-de-la-máquina>/`.

## Actualizar a una versión nueva

```bash
sudo -u napsis /opt/napsis-portal/deploy/deploy.sh
```

## Notas de consumo

- Gunicorn: 2 workers + 2 threads, recicla cada ~500 requests. Con esta app
  (uso interno, pocos clientes concurrentes completando el wizard) sobra.
- MySQL: tuning en `mysql-napsis-tuning.cnf` cappea el buffer pool en 128MB y
  apaga `performance_schema` (ahorra bastante RAM sola esa línea).
- Si con el tiempo notás que el server de juego sufre, lo primero para bajar
  más es `--workers 1` en el `.service` — para el volumen de esta app no
  debería notarse la diferencia.

## Logs

```bash
sudo journalctl -u napsis-portal -f      # gunicorn / Django
sudo tail -f /var/log/nginx/error.log    # nginx
```
