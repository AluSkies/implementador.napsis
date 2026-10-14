# Despliegue con Docker

La app corre como **un solo contenedor** (Gunicorn). No incluye base de datos: usa
el **MySQL existente** de Napsis. El proxy reverso y el TLS son los de la infra.

## Puesta en marcha

```bash
cp .env.docker.example .env.docker     # completar (secret key, MYSQL_*, dominio, SMTP...)
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
(3306 por defecto), las `EMAIL_*` y `DEFAULT_FROM_EMAIL` (sin SMTP no salen mails),
`IMPLEMENTATION_TEAM_EMAILS` y `GOOGLE_SHEETS_WEBHOOK_URL`, y `TRUSTED_PROXY_COUNT` (ver abajo).
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
    client_max_body_size 20M;
}
```

No hace falta servir `/static/` ni `/media/` aparte: los estáticos los sirve la app (WhiteNoise)
y los adjuntos también, **con login** — un cliente solo ve los suyos. No publicar `/media/`
desde el proxy.

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

```bash
docker compose pull && docker compose up -d
```

El CI (`.github/workflows/docker.yml`) corre los tests y publica la imagen en
`ghcr.io/aluskies/implementador-napsis` (`latest`, `sha-…` y `vX.Y.Z` por tag). El paquete es
privado: el host necesita `docker login ghcr.io` con un token de solo lectura (`read:packages`).

## Qué hay que saber

- **MySQL:** el usuario de la app necesita permisos de esquema (`CREATE/ALTER/DROP/INDEX`
  además del CRUD), si no `migrate` falla. Charset `utf8mb4`.
- **Backups:** además de MySQL, respaldar el volumen `media` (adjuntos de los clientes).
- **Más de una réplica:** poner `RUN_MIGRATIONS=0` en todas y correr
  `docker compose run --rm app python manage.py migrate` una sola vez por release.
- **Logs:** salen por stdout (`docker compose logs`). Un error 500 deja el traceback ahí.
