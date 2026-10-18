# Despliegue con Docker

La app corre como **un solo contenedor** (Gunicorn). No incluye base de datos: usa
el **MySQL existente** de Napsis. El proxy reverso y el TLS son los de la infra.

## Puesta en marcha

```bash
cp .env.docker.example .env.docker     # completar (secret key, MYSQL_*, dominio)
cp .env.mail.example .env.mail         # lo completa deploy cuando tenga el SMTP (ver deploy/CORREO.md)
docker compose pull                    # o `docker compose build` si se construye en el host
docker compose up -d
docker compose logs -f app             # ver el arranque
```

Al arrancar, el contenedor aplica las migraciones, carga los catálogos y módulos y crea
el superusuario inicial (`DJANGO_SUPERUSER_*`). Los tres pasos son idempotentes.

## Variables de entorno

**Obligatorias.** Si falta alguna el contenedor no arranca y lista cuáles faltan:

| Variable | Para qué |
|---|---|
| `DJANGO_SECRET_KEY` | Firma las sesiones. Sin ella cualquiera podría falsificarlas, por eso no hay valor por defecto. |
| `DJANGO_ALLOWED_HOSTS` | Dominio(s) de la app, ej. `implementacion.napsislatam.com`. Sin esto, todo da 400. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Mismo dominio con esquema, ej. `https://implementacion.napsislatam.com`. Sin esto, el login falla con 403. |
| `SITE_BASE_URL` | URL pública, para los links que salen en los mails. |
| `MYSQL_DB`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST` | La base. Sin ellas, la app guardaría los datos en un archivo dentro del contenedor y los perdería al reiniciar. |

**Opcionales:** `DJANGO_SUPERUSER_USERNAME/PASSWORD/EMAIL` (superusuario inicial), `MYSQL_PORT`
(3306 por defecto), `IMPLEMENTATION_TEAM_EMAILS` y `GOOGLE_SHEETS_WEBHOOK_URL`, y
`TRUSTED_PROXY_COUNT`, `DJANGO_FORCE_HTTPS`, `SECURE_HSTS_SECONDS` y `ERROR_ALERT_EMAILS` (ver abajo). El **correo saliente** (`EMAIL_*`, `DEFAULT_FROM_EMAIL`) va
aparte, en `.env.mail`: ver [CORREO.md](CORREO.md). Sin él la app funciona pero no envía mails.
`DJANGO_DEBUG` debe quedar en `false`.

## Proxy reverso

El contenedor escucha en `127.0.0.1:8000` (ver `ports` en `docker-compose.yml`). El proxy
de Napsis tiene que reenviar el subdominio ahí conservando `Host` y `X-Forwarded-Proto`:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    client_max_body_size 35M;     # un paso sube dos adjuntos de hasta 15 MB cada uno
    proxy_read_timeout 120s;      # importar una nómina grande puede tardar unos segundos
}
```

No hace falta servir `/static/` ni `/media/` aparte: los estáticos los sirve la app (WhiteNoise)
y los adjuntos también, **con login** — un cliente solo ve los suyos. No publicar `/media/`
desde el proxy.

## HTTPS obligatorio

En producción la app **exige HTTPS por sí misma** (no depende de que el proxy lo haga bien):
redirige `http` a `https`, marca las cookies de sesión y CSRF como `Secure` y manda HSTS.

- **El proxy tiene que terminar TLS y mandar `X-Forwarded-Proto: https`** (el ejemplo de arriba
  lo hace). Si no lo manda, la app cree que todo llega por http y entra en un **bucle de
  redirecciones**. También conviene que el proxy redirija 80 → 443 por su lado.
- **HSTS** arranca en 1 hora (`SECURE_HSTS_SECONDS=3600`). Cuando se confirme que todo anda por
  https, subirlo a un año (`31536000`) en `.env.docker`. No incluye subdominios.
- **Probar sin TLS** (solo un ensayo, nunca en producción): `DJANGO_FORCE_HTTPS=false`. Con
  los flags activos, el login **no anda por http** (la cookie es `Secure`).
- `/salud/` está exento del redirect (lo usa el healthcheck y se puede usar desde un monitor).

## Monitoreo y alertas

- **Healthcheck:** el contenedor consulta `/salud/` (que responde 200 solo si llega a la base),
  con el `Host` correcto, no solo si el puerto está abierto. `docker compose ps` muestra
  `healthy`/`unhealthy`. Docker no reinicia solo un contenedor `unhealthy`: para que alguien se
  entere, apuntar el monitor de infra a `https://<dominio>/salud/`.
- **Errores en un archivo de log:** cada error interno (500) y cada `logger.exception` del código
  (por ejemplo un mail que falla) queda guardado, con fecha y traceback, en `errores.log` dentro del
  volumen `napsis_logs` (sobrevive a los redeploys; rota a los 5 MB y guarda 5 archivos). Ver los
  últimos: `docker compose exec app tail -n 100 logs/errores.log`. Los tracebacks pueden incluir
  datos del error (por ejemplo un CUIL en un mensaje de la base): tratarlo como archivo interno.
  También salen por consola (`docker compose logs app`), que se pierde al recrear el contenedor.
- **Aviso por mail de un error 500: apagado por defecto.** Se activa definiendo `ERROR_ALERT_EMAILS`
  (lista separada por comas) y necesita el SMTP de `.env.mail`. Manda un mail por tipo de error
  cada 10 minutos, con el error y el traceback pero sin los datos del pedido.

## Límite de intentos de login

`/login/` y `/admin/login/` están expuestos a internet, así que la app bloquea la fuerza bruta
(django-axes): **5 intentos fallidos** con el mismo usuario desde la misma IP bloquean ese par
por **30 minutos** (un ingreso correcto reinicia la cuenta). Ver `AXES_*` en `config/settings.py`.

- **Necesita la IP real del cliente.** Detrás de un proxy, la app solo ve la IP del proxy: tiene que
  reenviar `X-Forwarded-For` (el ejemplo de nginx de arriba ya lo hace). `TRUSTED_PROXY_COUNT` es
  cuántos proxies *propios* hay delante de la app (default `1`; `2` si hay, por ejemplo, un CDN y
  después nginx). Se toma la entrada N-ésima desde la derecha, así que un `X-Forwarded-For`
  inventado por el cliente no sirve para evadir el límite. Si el valor no coincide con la
  realidad, el límite sigue funcionando pero por usuario (no por IP).
- **Desbloquear a alguien** antes de que pasen los 30 minutos:
  `docker compose exec app python manage.py axes_reset_username <usuario>`
  (o `axes_reset` para limpiar todos los bloqueos). También se ven y borran desde `/admin/`.

## Actualizar a una versión nueva

**Guía paso a paso (primer despliegue, actualizar y volver atrás): [RELEASE.md](RELEASE.md).**
En resumen: fijar la versión en `NAPSIS_IMAGE`, `docker compose pull && docker compose up -d`.

El CI (`.github/workflows/docker.yml`) corre el lint y los tests (también contra MySQL 8) en cada push.
**La imagen se publica solo cuando se crea un tag de versión** (`vX.Y.Z`): sale como
`ghcr.io/aluskies/implementador-napsis:vX.Y.Z` y `latest` pasa a apuntar a esa versión. Un push común a
`main` no construye ninguna imagen. Si los tests fallan, **no se publica nada**. El paquete es privado: el host necesita
`docker login ghcr.io` con un token de solo lectura (`read:packages`).

## Qué hay que saber

- **MySQL:** el usuario de la app necesita permisos de esquema (`CREATE/ALTER/DROP/INDEX`
  además del CRUD), si no `migrate` falla. Charset `utf8mb4`.
- **Backups:** además de MySQL, respaldar el volumen `napsis_media` (modelo de recibo y banner
  de los clientes). Comandos y restore en [RELEASE.md](RELEASE.md#backups-y-restore).
- **Valores de ejemplo:** el contenedor **no arranca** si `DJANGO_SECRET_KEY` es de ejemplo o
  tiene menos de 40 caracteres, o si `MYSQL_PASSWORD` / `DJANGO_SUPERUSER_PASSWORD` siguen en
  `cambiar`. Es a propósito: son los textos de relleno de `.env.docker.example`.
- **Más de una réplica:** poner `RUN_MIGRATIONS=0` en todas y correr
  `docker compose run --rm app python manage.py migrate` una sola vez por release.
- **Logs:** salen por stdout (`docker compose logs app`) y los errores además quedan en
  `errores.log` (ver "Monitoreo y alertas").
