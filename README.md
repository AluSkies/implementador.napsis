# Portal de Implementación Napsis

Webapp Django para el relevamiento de autoservicio de nuevos clientes de Napsis. Reemplaza los 5 Excel de relevamiento (Datos de Nómina, Documentos Legajo Digital, Importación de Nómina, Información Pre Implementación, Licencias y Novedades) por un wizard web con link único por cliente, y notifica al equipo de implementación al enviarse.

## Estructura

- `clients/` — dos entidades separadas:
  - `Cliente`: la empresa (Nombre, CUIT(s) separados por coma). Persistente: un mismo Cliente puede tener varias Implementaciones a lo largo del tiempo.
  - `Implementacion`: un proceso puntual de relevamiento para un Cliente — tiene su propio token/link único, estado (`Pendiente` / `Cumplida` / `Cancelada`), todos los datos de contacto y configuración relevados en el wizard, y el pedido de revisión del cliente (`revision_solicitada`, `pedir_revision()`, `anular()`).
  - Además: `PersonaRol`, `Sucursal`, `Modulo`, `ImplementacionModulo` (todos FK a `Implementacion`, no a `Cliente`).
- `catalog/` — catálogos: TipoLicencia (16), TipoNovedad (10), TipoDocumento + CampoDocumento (16 tipos de legajo digital con sus campos). Se cargan con `manage.py seed_catalogos` (a partir del relevamiento original), no con una migración.
- `onboarding/` — el wizard público (9 pasos) y las tablas de activación por implementación (ImplementacionLicencia, ImplementacionNovedad, ImplementacionTipoDocumento).
- `employees/` — Empleado, ImportBatch (ambos FK a Implementacion), parser/validador de la plantilla masiva (`employees/services.py`) y generador de la plantilla vacía descargable.
- `notifications/` — envío del mail de resumen y del mail de "pedido de contacto" al equipo de implementación, y el POST a un webhook de Google Apps Script para el dump a Sheets.
- `dashboard/` — panel interno con login: listado de implementaciones, ficha de cliente con su historial, generación de links, anular/reiniciar una implementación, atender pedidos de revisión.

Todos los datos que se completan en el wizard (roles, sucursales, módulos, licencias, novedades, documentos de legajo, empleados) cuelgan de `Implementacion`, no de `Cliente` — así una misma empresa puede repetir el proceso en el futuro sin arrastrar datos de una ronda anterior.

## Puesta en marcha (desarrollo)

```bash
python -m venv venv
venv/Scripts/pip install -r requirements.txt
venv/Scripts/python manage.py migrate
venv/Scripts/python manage.py seed_catalogos
venv/Scripts/python manage.py seed_modulos
venv/Scripts/python manage.py createsuperuser
venv/Scripts/python manage.py runserver
```

Copiá `.env.example` a `.env` y completá los valores. Los catálogos y módulos se cargan con `seed_catalogos` / `seed_modulos` (idempotentes; también los corre `build.sh` en cada deploy).

- Panel interno: `http://localhost:8000/panel/` (requiere login).
- Wizard de cliente: se accede vía el link único que genera el panel (`/r/<token>/`), no tiene login.

## Variables de entorno (`.env`)

- `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`
- `DJANGO_EMAIL_BACKEND` (usa el backend de consola en dev; en producción configurar SMTP con `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, etc.)
- `IMPLEMENTATION_TEAM_EMAILS` — lista separada por comas que recibe el mail de resumen al completarse una implementación.
- `GOOGLE_SHEETS_WEBHOOK_URL` — URL del Google Apps Script Web App que appendea la fila al Sheet de seguimiento (ver abajo). Si queda vacío, ese paso se omite (se loggea, no rompe el flujo).
- `SITE_BASE_URL` — usado para armar links absolutos en los mails cuando no hay `request` disponible.
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` — opcionales. Si `POSTGRES_DB` está seteado, la app usa Postgres en vez de SQLite (ver "Producción / self-hosting").

## Integración con Google Sheets

El envío final hace un `POST` con JSON al `GOOGLE_SHEETS_WEBHOOK_URL`. Para armarlo:

1. Crear un Google Sheet de seguimiento.
2. Extensiones → Apps Script, y publicar un `doPost(e)` que parsee `e.postData.contents` (JSON) y haga `sheet.appendRow([...])` con los campos que se necesiten (el payload incluye: razón social, CUIT, mail/teléfono de contacto, módulos, licencias, novedades, documentos activos, cantidad de empleados/sucursales, roles).
3. Implementar como aplicación web (acceso "Cualquier usuario"), copiar la URL del deployment y pegarla en `GOOGLE_SHEETS_WEBHOOK_URL`.

## Producción / self-hosting

Corre directo sobre el hardware/VM que asigne Infra, sin Docker — si más adelante deciden containerizarlo igual pueden, pero no es un requisito de la app.

- `DEBUG=false`, `DJANGO_ALLOWED_HOSTS` con el dominio/IP real.
- Base de datos: seteando `POSTGRES_DB` (+ `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`) en el entorno, la app usa Postgres automáticamente en vez de SQLite — no hace falta tocar código. `psycopg2-binary` ya está en `requirements.txt`.
- Server WSGI: `gunicorn` ya está en `requirements.txt`. Se levanta con `gunicorn config.wsgi:application --bind 127.0.0.1:8000` (puerto interno — no expuesto directo a internet).
- Reverse proxy: como ese server ya sirve el dominio y el portal Napsis, la forma esperada de integrarlo es que el webserver que ya está corriendo (IIS/nginx/Apache, lo que usen) haga de reverse proxy hacia `127.0.0.1:8000` (por subdominio o path), igual que cualquier otro servicio que ya convivan ahí. La app no necesita ni intenta pelear por el puerto 80/443.
- Estáticos: correr `python manage.py collectstatic` antes de arrancar, y servir `STATIC_ROOT` (`staticfiles/`) desde el mismo reverse proxy.
- `MEDIA_ROOT` (`media/`) necesita un volumen/carpeta persistente — ahí quedan los adjuntos (banners, modelos de recibo, documentos de legajo, archivos de importación).
- Proceso persistente: en Linux, un servicio `systemd` corriendo gunicorn (con `--workers` según CPU) es lo estándar; en Windows Server, la alternativa más simple a gunicorn es `waitress` (`pip install waitress`, `waitress-serve --port=8000 config.wsgi:application`) corriendo como servicio de Windows (NSSM o similar).
- SMTP real para el envío de mails (hoy usa el backend de consola en dev).

## Cómo probar el flujo completo

1. Entrar a `/panel/`, loguearse, crear una implementación (elegís un Cliente existente o cargás uno nuevo con Nombre + CUIT(s); esto genera el link único).
2. Abrir el link generado en una pestaña sin sesión (simula al cliente) y completar los 9 pasos.
3. En el paso de empleados, se puede descargar la plantilla vacía, completarla y subirla, o cargar empleados a mano.
4. Al enviar el paso 9, la implementación pasa a estado "Cumplida", se dispara el mail (visible en consola en dev) y el POST a Sheets si está configurado.
5. Con el mismo link, el cliente puede volver a entrar y ver todo en solo lectura, y pedir que lo contacten ("Pedir que me contacten") — eso también manda un mail al equipo.
6. Desde `/panel/`, en la ficha de la implementación, se puede reiniciar el link, anular la implementación (pasa a "Cancelada" y el cliente ya no puede completarla), y marcar como atendido un pedido de contacto.
