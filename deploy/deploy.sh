#!/usr/bin/env bash
# Actualiza el portal ya instalado en /opt/napsis-portal. Correr como el
# usuario "napsis" (o con sudo -u napsis).
set -o errexit

cd /opt/napsis-portal

git pull
source venv/bin/activate
pip install -r requirements.txt --quiet
python manage.py collectstatic --no-input
python manage.py migrate

deactivate
sudo systemctl restart napsis-portal
