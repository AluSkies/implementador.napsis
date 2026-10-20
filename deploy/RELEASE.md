# Cómo desplegar el portal: primera vez, actualizar y volver atrás

Guía pensada para quien nunca desplegó esta app. Los comandos se corren **en el servidor**, dentro
de la carpeta donde está `docker-compose.yml`. Para el detalle de cada variable ver
[DOCKER.md](DOCKER.md), y para el correo [CORREO.md](CORREO.md).

## La idea en tres líneas

1. Cada versión de la app es una **imagen de Docker** con una etiqueta (`v1.0.0`). La construye
   sola GitHub cuando se publica una versión, y **solo si pasan todos los tests**.
2. El servidor no compila nada: **descarga** esa imagen (`docker compose pull`) y la **arranca**
   (`docker compose up -d`).
3. Los datos no viven en la imagen: están en el **MySQL** de Napsis y en el volumen `napsis_media`.
   Por eso se puede cambiar de versión (o volver a una anterior) sin perder datos, **siempre que
   haya un backup** de esas dos cosas.

## Antes de empezar (lo que tiene que dar infraestructura)

- [ ] Un servidor con **Docker** y **Docker Compose 2.24 o más nuevo** (`docker compose version`).
- [ ] Una base en el **MySQL 8** de Napsis (charset `utf8mb4`) y un usuario con permisos de esquema
      (`CREATE`, `ALTER`, `DROP`, `INDEX` además de `SELECT/INSERT/UPDATE/DELETE`).
- [ ] Un **dominio** y un proxy (nginx, etc.) con **certificado TLS** que reenvíe al puerto
      `127.0.0.1:8000` del servidor, mandando `Host`, `X-Forwarded-For` y **`X-Forwarded-Proto: https`**
      (ver el ejemplo en DOCKER.md). El portal exige HTTPS: sin ese header entra en bucle de redirecciones.
- [ ] Una cuenta **SMTP** para los mails (ver CORREO.md). Sin ella el portal funciona pero no manda mails.
- [ ] Un **token de GitHub** de solo lectura (`read:packages`) para que el servidor pueda bajar la imagen.
- [ ] Una política de **backups** del MySQL y del volumen `napsis_media` (ver más abajo).

## Primer despliegue

```bash
# 1. Tener a mano los archivos de configuración (viven solo en el servidor, nunca se suben a GitHub)
cp .env.docker.example .env.docker      # completar: clave secreta, dominio, MySQL, superusuario
cp .env.mail.example   .env.mail        # completar cuando se tenga el SMTP (puede quedar para después)

# 2. Fijar QUÉ versión se despliega, en un archivo llamado .env junto al docker-compose.yml
echo "NAPSIS_IMAGE=ghcr.io/aluskies/implementador-napsis:v1.0.0" > .env

# 3. Entrar al registro de imágenes (te pide usuario y el token de solo lectura)
docker login ghcr.io

# 4. Descargar y arrancar
docker compose pull
docker compose up -d
docker compose logs -f app              # mirar el arranque; Ctrl+C para salir (no frena la app)
```

La clave secreta se genera con `python -c "import secrets; print(secrets.token_urlsafe(50))"` (puede
hacerse en cualquier computadora con Python). **El contenedor se niega a arrancar** si quedó algún
valor de ejemplo (`cambiar`, `generar-una-clave…`) o la clave es corta: es a propósito, para que
nadie publique el portal con una contraseña que está escrita en el repositorio.

En los logs tiene que verse algo así, y después `Listening at: http://0.0.0.0:8000`:

```
Running migrations: ... OK          ← crea las tablas en el MySQL
Catálogo de módulos listo ...       ← carga los módulos y catálogos la primera vez
Superusuario 'admin' creado.
```

**Verificar que quedó bien** (la lista completa está al final):

```bash
docker compose ps                        # el estado tiene que decir "healthy" (tarda ~1 minuto)
curl -i https://<dominio>/salud/         # 200 y {"estado": "ok"}
```

Después, entrar a `https://<dominio>/login/` con el superusuario y **cambiar su contraseña** desde
«Mi perfil». Si se quiere, borrar `DJANGO_SUPERUSER_PASSWORD` de `.env.docker`.

## Actualizar a una versión nueva

1. **Hacer un backup** de MySQL y del volumen (ver más abajo). Siempre, antes de actualizar: algunas
   versiones traen cambios en las tablas que se aplican solos al arrancar y no se pueden deshacer.
2. Cambiar la versión en el archivo `.env`: `NAPSIS_IMAGE=ghcr.io/aluskies/implementador-napsis:v0.4.0`
3. Descargar y reemplazar:
   ```bash
   docker compose pull
   docker compose up -d        # recrea el contenedor; hay un corte de unos segundos
   docker compose logs -f app  # confirmar que migró y arrancó sin errores
   ```
4. Verificar con la lista de abajo.

**Siempre fijar un número de versión (`vX.Y.Z`)** y no usar `latest`: `latest` apunta a la
última versión publicada y nadie sabe cuál es la que está corriendo. La imagen se construye solo cuando
se crea un tag de versión; un push común a `main` no genera nada para desplegar.

## Volver atrás (rollback)

Si la versión nueva anda mal:

1. En `.env` volver a poner la versión anterior (`NAPSIS_IMAGE=…:v0.3.0`).
2. `docker compose pull && docker compose up -d`.

⚠️ Esto vuelve el **código**, pero **no deshace los cambios en las tablas** que la versión nueva ya
aplicó. Si la versión nueva no tenía cambios de tablas, alcanza. Si los tenía y la versión vieja no
anda con ellas, hay que **restaurar el backup** de MySQL que se hizo antes de actualizar (por eso el
paso 1). Ante la duda: restaurar el backup.

## Backups y restore

Hay que respaldar **las dos cosas juntas** (la base referencia a los archivos).

**MySQL** (lo puede cubrir la rutina de backup de infraestructura; confirmar que incluye la base del portal):

```bash
mysqldump --single-transaction --routines -h <host> -u <usuario> -p <base> > portal_$(date +%F).sql
```

**Volumen `napsis_media`** (modelo de recibo y banner que suben los clientes):

```bash
docker run --rm -v napsis_media:/data -v "$PWD":/respaldo alpine tar czf /respaldo/media_$(date +%F).tgz -C /data .
```

**Restore** (con la app detenida, `docker compose down`, y **sin** la opción `-v`: `down -v` borra el volumen):

```bash
mysql -h <host> -u <usuario> -p <base> < portal_YYYY-MM-DD.sql
docker run --rm -v napsis_media:/data -v "$PWD":/respaldo alpine sh -c "cd /data && tar xzf /respaldo/media_YYYY-MM-DD.tgz"
docker compose up -d
```

Un backup que nunca se restauró no es un backup: conviene **probar un restore** en un entorno de prueba antes del lanzamiento.

## Lista de verificación después de desplegar

- [ ] `docker compose ps` dice `healthy` y `https://<dominio>/salud/` responde 200.
- [ ] `http://<dominio>/` redirige a `https://` y el candado del navegador está bien.
- [ ] Se puede ingresar al panel con el superusuario.
- [ ] Mail de prueba (comando en CORREO.md) y, mejor, crear una implementación con tu propio mail
      como «Mail del cliente»: llega la invitación y el link abre la página para crear la contraseña.
- [ ] Subir un PDF de más de 1 MB como modelo de recibo y un Excel de nómina (prueba los límites del proxy).
- [ ] Provocar un bloqueo de login (5 intentos fallidos) y comprobar que se desbloquea (o ver DOCKER.md).
- [ ] Hay un monitor externo mirando `/salud/`, y alguien sabe dónde ver los errores: `docker compose exec app tail -n 100 logs/errores.log`.

## Si algo sale mal

| Síntoma | Causa probable |
|---|---|
| El contenedor se reinicia solo | `docker compose logs app`: casi siempre falta una variable, quedó un valor de ejemplo, o no conecta al MySQL (host, usuario, permisos). |
| Error 400 en todo el sitio | `DJANGO_ALLOWED_HOSTS` no incluye el dominio. |
| Login con error 403 (CSRF) | `DJANGO_CSRF_TRUSTED_ORIGINS` sin el dominio con `https://`. |
| El navegador queda cargando / «demasiadas redirecciones» | El proxy no manda `X-Forwarded-Proto: https`. |
| Se puede ver el login pero no ingresar (por http) | Es esperado: las cookies son `Secure`. Entrar siempre por https. |
| 502 / 504 del proxy | El contenedor no está sano o una importación de nómina tardó más que `proxy_read_timeout`. |
| No llegan los mails | Falta o está mal `.env.mail`; ver CORREO.md y el log (`docker compose logs app`). |
| Error 413 al subir un archivo | `client_max_body_size` del proxy es chico (usar 35M). |
| Un cliente reporta "algo salió mal" (error 500) | Mirar `docker compose exec app tail -n 100 logs/errores.log`: ahí está el error con su traceback. |
| Un cliente quedó bloqueado en el login | `docker compose exec app python manage.py axes_reset_username <usuario>` |
