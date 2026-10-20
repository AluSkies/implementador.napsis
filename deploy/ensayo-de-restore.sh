#!/bin/bash
# Ensayo de backup y restore, de punta a punta, con Docker (no toca ningún entorno real).
#
# Arma un MySQL 8 y la imagen de la app descartables, carga datos y un adjunto, hace el backup
# (mysqldump + tar del volumen de adjuntos), DESTRUYE todo, restaura en un entorno vacío y compara.
# Si termina con "IDÉNTICO", el procedimiento de deploy/RELEASE.md (sección Backups) funciona.
#
# Uso, desde la raíz del repositorio:   bash deploy/ensayo-de-restore.sh
# Necesita Docker y acceso a internet (baja mysql:8.4 y alpine). Tarda unos minutos.
set -u
export MSYS_NO_PATHCONV=1     # Git Bash en Windows: no convertir las rutas de los volúmenes
NET=ens-red
DB=napsis_portal
TMP=$(mktemp -d)
command -v cygpath >/dev/null 2>&1 && TMP=$(cygpath -m "$TMP")   # Git Bash: ruta que Docker de Windows entienda
KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))" 2>/dev/null || python -c "import secrets; print(secrets.token_urlsafe(50))")

cat > "$TMP/ens.env" <<EOF
DJANGO_SECRET_KEY=$KEY
DJANGO_ALLOWED_HOSTS=localhost
DJANGO_CSRF_TRUSTED_ORIGINS=https://localhost
SITE_BASE_URL=https://localhost
MYSQL_DB=$DB
MYSQL_USER=napsis
MYSQL_PASSWORD=ensayo-clave-larga-9
MYSQL_HOST=ens-mysql
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_EMAIL=admin@ejemplo.com
DJANGO_SUPERUSER_PASSWORD=Ensayo-Admin-2026-Xq
TRUSTED_PROXY_COUNT=0
DJANGO_FORCE_HTTPS=false
EOF

limpiar() {
  docker rm -f ens-app ens-mysql >/dev/null 2>&1
  docker volume rm ens_media ens_logs ens_mysql >/dev/null 2>&1
  docker network rm $NET >/dev/null 2>&1
}
esperar_mysql() {
  # La imagen de MySQL arranca un servidor temporal para inicializarse y lo reinicia: hay que esperar al definitivo.
  for _ in $(seq 1 80); do
    listos=$(docker logs ens-mysql 2>&1 | grep -c "ready for connections")
    if [ "$listos" -ge 2 ] && docker exec ens-mysql mysql -unapsis -pensayo-clave-larga-9 -h127.0.0.1 -e "select 1" $DB >/dev/null 2>&1; then return 0; fi
    sleep 3
  done
  echo "MySQL no arrancó"; return 1
}
esperar_app() {
  for _ in $(seq 1 60); do docker exec ens-app python docker/healthcheck.py >/dev/null 2>&1 && return 0; sleep 3; done
  echo "La app no quedó sana"; docker logs --tail 30 ens-app; return 1
}
levantar_mysql() {
  docker run -d --name ens-mysql --network $NET -v ens_mysql:/var/lib/mysql \
    -e MYSQL_ROOT_PASSWORD=ensayo-root -e MYSQL_DATABASE=$DB -e MYSQL_USER=napsis -e MYSQL_PASSWORD=ensayo-clave-larga-9 \
    mysql:8.4 --character-set-server=utf8mb4 --collation-server=utf8mb4_0900_ai_ci >/dev/null
}
levantar_app() {
  docker run -d --name ens-app --network $NET --env-file "$TMP/ens.env" -v ens_media:/app/media -v ens_logs:/app/logs napsis-ensayo >/dev/null
}
foto() {   # imprime lo que se compara antes y después: contenido del adjunto y conteos
  docker exec ens-app python manage.py shell -c "
import hashlib
from django.contrib.auth.models import User
from clients.models import Cliente, Implementacion
from catalog.models import TipoLicencia
i = Implementacion.objects.get(cliente__nombre='Empresa Ensayo')
print('SHA', hashlib.sha256(i.modelo_recibo.read()).hexdigest(), 'RUTA', i.modelo_recibo.name)
print('CONTEOS clientes=%d implementaciones=%d licencias=%d usuarios=%d' % (Cliente.objects.count(), Implementacion.objects.count(), TipoLicencia.objects.count(), User.objects.count()))
print('LOGIN_ADMIN', User.objects.get(username='admin').check_password('Ensayo-Admin-2026-Xq'))
" 2>&1 | grep -E "^(SHA|CONTEOS|LOGIN)"
}

trap 'limpiar; docker rmi -f napsis-ensayo >/dev/null 2>&1; rm -rf "$TMP"' EXIT
limpiar
echo "== 0. Imagen de la app"; docker build -q -t napsis-ensayo . | tail -1
docker network create $NET >/dev/null

echo "== 1. Entorno original: MySQL + app"
levantar_mysql; esperar_mysql || exit 1
levantar_app; esperar_app || exit 1

echo "== 2. Datos de prueba (una empresa, una implementación y su PDF adjunto)"
docker exec ens-app python manage.py shell -c "
from django.core.files.base import ContentFile
from clients.models import Cliente, Implementacion
c = Cliente.objects.create(nombre='Empresa Ensayo', razon_social='Ensayo SA', cuits='30-71098766-8')
i = Implementacion.objects.create(cliente=c, mail_contacto='ensayo@ejemplo.com', telefono='011-5555-0000')
i.modelo_recibo.save('recibo_ensayo.pdf', ContentFile(b'%PDF-1.4 ensayo de restore ' + b'x' * 5000))
" >/dev/null 2>&1
foto | tee "$TMP/antes.txt"

echo "== 3. BACKUP (mysqldump + tar del volumen de adjuntos)"
docker exec ens-mysql mysqldump --single-transaction --routines -uroot -pensayo-root $DB 2>/dev/null > "$TMP/portal.sql"
docker run --rm -v ens_media:/data alpine tar czf - -C /data . > "$TMP/media.tgz"
echo "dump: $(wc -c < "$TMP/portal.sql") bytes; adjuntos: $(wc -c < "$TMP/media.tgz") bytes"

echo "== 4. DESASTRE: se borran los contenedores, la base y los adjuntos"
docker rm -f ens-app ens-mysql >/dev/null
docker volume rm ens_media ens_logs ens_mysql >/dev/null

echo "== 5. RESTORE en un entorno vacío"
levantar_mysql; esperar_mysql || exit 1
docker exec -i ens-mysql mysql -uroot -pensayo-root $DB < "$TMP/portal.sql" 2>/dev/null && echo "base restaurada"
docker volume create ens_media >/dev/null
docker run --rm -i -v ens_media:/data alpine tar xzf - -C /data < "$TMP/media.tgz" && echo "adjuntos restaurados"
levantar_app; esperar_app || exit 1

echo "== 6. Verificación"
foto > "$TMP/despues.txt"; cat "$TMP/despues.txt"
if diff "$TMP/antes.txt" "$TMP/despues.txt" >/dev/null; then
  echo "IDÉNTICO: los datos, el catálogo, el login del admin y el adjunto se restauraron sin diferencias."
else
  echo "HAY DIFERENCIAS entre antes y después del restore:"; diff "$TMP/antes.txt" "$TMP/despues.txt"; exit 1
fi
