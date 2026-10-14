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

## Roles

| Rol | Cuenta | Qué puede |
|---|---|---|
| **Admin** | superusuario | Todo lo del implementador, más alta, modificación y baja de implementadores (en el panel, `/panel/implementadores/`). |
| **Implementador** | staff, sin ser superusuario | Trabajar el panel: implementaciones, clientes, nómina, historial. |
| **Cliente** | sin `is_staff` | Solo el wizard y la consulta de sus propias implementaciones. |

El primer Admin se crea con `createsuperuser` (o con `ensure_superuser` y `DJANGO_SUPERUSER_*` donde no hay shell). Los implementadores los crea después un Admin desde el panel: la contraseña se genera sola y se muestra una única vez. La baja es lógica (la cuenta no puede ingresar pero se conserva, así no se pierde a quién se atribuyen las implementaciones que creó). Un implementador que entra a una sección de Admin recibe un 403.

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

Copiá `.env.example` a `.env` y completá los valores. Los catálogos y módulos se cargan con `seed_catalogos` / `seed_modulos` (idempotentes; el entrypoint de Docker y `deploy/deploy.sh` los corren en cada arranque/deploy).

- Panel interno: `http://localhost:8000/panel/` (requiere login).
- Wizard de cliente: se accede vía el link único que genera el panel (`/r/<token>/`), no tiene login.

## Tests

```bash
venv/Scripts/python manage.py test                   # toda la suite (~10 segundos)
venv/Scripts/python manage.py test dashboard         # solo una app
venv/Scripts/python manage.py test --durations=10    # los 10 más lentos
```

Hay tests por app, en paquetes `tests/`. La base de test arranca vacía (los catálogos se cargan con `seed_catalogos`/`seed_modulos`, no con migraciones), así que cada test crea lo que necesita.

Al correr los tests `settings.py` cambia el hasher de contraseñas a uno rápido. El de producción (PBKDF2) es lento a propósito, y como cada test crea usuarios y se loguea, con él la suite tardaba más de 10 minutos en vez de segundos. Un test verifica que ese cambio nunca se active fuera de los tests.

## Variables de entorno (`.env`)

- `DJANGO_SECRET_KEY` — **obligatoria con `DJANGO_DEBUG=false`** (sin ella la app no arranca). `DJANGO_DEBUG` (default `false`; en dev ya viene en `true` por el `.env`).
- `DJANGO_ALLOWED_HOSTS` y `DJANGO_CSRF_TRUSTED_ORIGINS` (con `https://`) — el dominio real; sin ellos hay 400/403.
- `DJANGO_EMAIL_BACKEND` (usa el backend de consola en dev; en producción configurar SMTP con `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, etc.)
- `IMPLEMENTATION_TEAM_EMAILS` — lista separada por comas que recibe el mail de resumen al completarse una implementación.
- `TRUSTED_PROXY_COUNT` — cuántos proxies reverso propios hay delante de la app (default `1` en producción, `0` en desarrollo). Lo usa el límite de intentos de login para saber la IP real del cliente.
- `GOOGLE_SHEETS_WEBHOOK_URL` — URL del Google Apps Script Web App que appendea la fila al Sheet de seguimiento (ver abajo). Si queda vacío, ese paso se omite (se loggea, no rompe el flujo).
- `SITE_BASE_URL` — usado para armar links absolutos en los mails cuando no hay `request` disponible.
- `MYSQL_DB`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, `MYSQL_PORT` — la base en producción. Si `MYSQL_DB` no está seteado, la app usa SQLite (desarrollo y tests).
- `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, `DJANGO_SUPERUSER_EMAIL` — opcionales; `manage.py ensure_superuser` crea ese superusuario si no existe (útil donde no hay shell).

## Integración con Google Sheets

El envío final hace un `POST` con JSON al `GOOGLE_SHEETS_WEBHOOK_URL`. Para armarlo:

1. Crear un Google Sheet de seguimiento.
2. Extensiones → Apps Script, y publicar un `doPost(e)` que parsee `e.postData.contents` (JSON) y haga `sheet.appendRow([...])` con los campos que se necesiten (el payload incluye: razón social, CUIT, mail/teléfono de contacto, módulos, licencias, novedades, documentos activos, cantidad de empleados/sucursales, roles).
3. Implementar como aplicación web (acceso "Cualquier usuario"), copiar la URL del deployment y pegarla en `GOOGLE_SHEETS_WEBHOOK_URL`.

## Producción

Motor de base de datos: **MySQL 8+** (`utf8mb4`, driver PyMySQL). Hay dos formas de desplegarlo, con la misma app:

- **Docker** (`deploy/DOCKER.md`): un contenedor con Gunicorn contra el MySQL existente. El CI (`.github/workflows/docker.yml`) corre los tests y publica la imagen en `ghcr.io`.
- **Directo sobre Ubuntu** (`deploy/README.md`): systemd + nginx + MySQL, con el tuning de recursos incluido.

En ambos casos:

- `DJANGO_DEBUG=false` y las variables obligatorias de arriba (el contenedor valida que estén todas y avisa cuáles faltan).
- El proxy reverso (que pone el TLS) reenvía el dominio a Gunicorn conservando `Host` y `X-Forwarded-Proto`. Se pide un subdominio propio, separado del portal WordPress.
- Estáticos: los sirve la propia app (WhiteNoise, tras `collectstatic`); no hace falta configurarlos en el proxy.
- Adjuntos subidos (`MEDIA_ROOT`, `media/`): requieren un volumen/carpeta persistente y entrar en el backup. Los sirve la app con login (`/media/`): el equipo ve cualquiera y un cliente solo los suyos. **No publicar `/media/` desde el proxy.**
- Después de cada `migrate` hay que correr `seed_catalogos` y `seed_modulos` (idempotentes).
- **Límite de intentos de login** (django-axes): 5 fallos seguidos con el mismo usuario desde la misma IP bloquean ese par por 30 minutos, en `/login/` y `/admin/login/`. Requiere que el proxy reenvíe `X-Forwarded-For` (ver `deploy/DOCKER.md`). Para desbloquear a alguien: `manage.py axes_reset_username <usuario>`.
- SMTP real para los mails (en dev se usa el backend de consola).

## Qué exige el wizard antes de poder enviar

El cliente no puede enviar el relevamiento hasta completar (el paso 9 lista lo que falta, con link a cada paso, y el botón queda deshabilitado; el servidor lo valida igual):

- **Razón social y CUIT** de la empresa (paso 1). El implementador puede cargarlos al crear la implementación; si no, los completa el cliente. Los CUIT se validan con su dígito verificador (acepta varios, separados por coma).
- **Roles** (si hay Recibo Digital o Legajos): al menos un Apoderado/Firmante, un Liquidador y un Admin. de RRHH.
- **Modelo de recibo** en PDF (si hay Recibo Digital).
- **Nómina**: al menos un empleado.

**Condiciones del proceso.** Al crear la implementación (y después desde su ficha) el equipo decide qué deja fijo y qué decide el cliente. Cada dato se bloquea **al completarlo**; si se deja vacío, lo decide el cliente:

- **Tipo de firma** (electrónica o digital) y **nomenclatura de los recibos PDF**: si el implementador los define, el cliente los ve en el paso 4 pero no los puede cambiar (ni editando el formulario a mano).
- **Solo Área única**: bloquea la segmentación del liquidador.
- **Máximo de personas con rol** (de 3 a 6): cuántas filas ve el cliente en el paso de roles. El mínimo es 3 porque tiene que cargar un Apoderado/Firmante, un Liquidador y un Admin. de RRHH.

En el alta del panel estas condiciones están plegadas bajo **Opciones avanzadas**. El tipo de empresa (ART o comercial) no está: se agrega cuando se defina qué cambia en el proceso.

**Fecha de implementación.** En el paso 9 el cliente puede pedir una fecha (es opcional), pero no antes de **10 días hábiles** desde hoy (lunes a viernes; no se descuentan feriados). Si el equipo ya había puesto una fecha, esa se respeta tal cual. El equipo de implementación puede poner cualquier fecha desde el panel, sin ese mínimo.

Cada implementación tiene un **implementador asignado** (por defecto quien la crea, se elige en el alta y se puede reasignar). Es quien lleva la implementación y, además de la lista `IMPLEMENTATION_TEAM_EMAILS`, recibe sus notificaciones.

## Cómo probar el flujo completo

1. Entrar a `/panel/`, loguearse, crear una implementación (elegís un Cliente existente o cargás uno nuevo con Nombre + CUIT(s); esto genera el link único).
2. Abrir el link generado en una pestaña sin sesión (simula al cliente) y completar los 9 pasos.
3. En el paso de empleados, se puede descargar la plantilla vacía, completarla y subirla, o cargar empleados a mano.
4. Al enviar el paso 9, la implementación queda "Pendiente - Completo por cliente" (el cliente ya cargó todo; sigue pendiente porque el trabajo de implementar es del equipo), se dispara el mail (visible en consola en dev) y el POST a Sheets si está configurado. Pasa a "Cumplida" recién cuando el equipo la marca como cumplida desde el panel.
5. Con el mismo link, el cliente puede volver a entrar y ver todo en solo lectura, y pedir que lo contacten ("Pedir que me contacten") — eso también manda un mail al equipo.
6. Desde `/panel/`, en la ficha de la implementación, se puede reiniciar el link, anular la implementación (pasa a "Cancelada" y el cliente ya no puede completarla), y marcar como atendido un pedido de contacto.
