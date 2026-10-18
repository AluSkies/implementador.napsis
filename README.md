# Portal de Implementación Napsis

Webapp Django para el relevamiento de autoservicio de nuevos clientes de Napsis. Reemplaza los 5 Excel de relevamiento (Datos de Nómina, Documentos Legajo Digital, Importación de Nómina, Información Pre Implementación, Licencias y Novedades) por un wizard web con link único por cliente, y notifica al equipo de implementación al enviarse.

**Para entender el código:** los diagramas (capas, apps, modelo de datos, pasos del wizard, estados, recorrido completo, validación y congelado, eventos y despliegue) están en [`docs/arquitectura.md`](docs/arquitectura.md).

## Estructura

- `clients/` — dos entidades separadas:
  - `Cliente`: la empresa (Nombre, CUIT(s) separados por coma). Persistente: un mismo Cliente puede tener varias Implementaciones a lo largo del tiempo.
  - `Implementacion`: un proceso puntual de relevamiento para un Cliente — tiene su propio token/link único, estado (`Pendiente` / `Cumplida` / `Cancelada`), todos los datos de contacto y configuración relevados en el wizard, y el pedido de revisión del cliente (`revision_solicitada`, `pedir_revision()`, `anular()`).
  - Además: `PersonaRol`, `Sucursal`, `Modulo`, `ImplementacionModulo` (todos FK a `Implementacion`, no a `Cliente`).
- `automatizacion/` — actores, registro de eventos (solo se agrega) y configuración congelada.
- `catalog/` — catálogos: TipoLicencia (16), TipoNovedad (10), TipoDocumento + CampoDocumento (16 tipos de legajo digital con sus campos). Se cargan con `manage.py seed_catalogos` (a partir del relevamiento original), no con una migración.
- `onboarding/` — el wizard público (10 pasos), las acciones (alta, envío, validar, devolver, cumplir) y los servicios de guardado y las tablas de activación por implementación (ImplementacionLicencia, ImplementacionNovedad, ImplementacionTipoDocumento).
- `employees/` — Empleado, ImportBatch (ambos FK a Implementacion), parser/validador de la plantilla masiva (`employees/services.py`) y generador de la plantilla vacía descargable.
- `notifications/` — mails al equipo (resumen y "pedido de contacto") y al cliente (invitación, confirmaciones).
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

Copiá `.env.example` a `.env` y completá los valores. Los catálogos y módulos se cargan con `seed_catalogos` / `seed_modulos` (idempotentes; el entrypoint de Docker y `deploy/sin-docker/deploy.sh` los corren en cada arranque/deploy).

- Panel interno: `http://localhost:8000/panel/` (requiere login).
- Wizard de cliente: se accede vía el link único que genera el panel (`/r/<token>/`), no tiene login.

## Tests

```bash
venv/Scripts/python manage.py test                   # toda la suite (~45 s)
venv/Scripts/python manage.py test --parallel        # en paralelo, con todos los núcleos (~30 s)
venv/Scripts/python manage.py test onboarding        # una app
venv/Scripts/python manage.py test onboarding.tests.firma                  # un paquete (~5 s)
venv/Scripts/python manage.py test onboarding.tests.firma.test_servicio    # un módulo
venv/Scripts/python manage.py test onboarding.tests.firma --keepdb         # sin recrear la base de test
venv/Scripts/python manage.py test --durations=10    # los 10 más lentos
```

**Dónde está cada cosa.** Hay tests por app, en paquetes `tests/`, y dentro de cada app agrupados por tema para poder correr solo lo que se tocó:

- `onboarding/tests/`: `wizard/` (cada paso y el envío), `firma/`, `revision/` (validar, devolver, cumplir, invalidación y reglas de validación), `liquidaciones/`, `imagenes/`, `formularios/`, `servicios/` (guardado, pendientes, empleados), `acciones/` (alta, estado y envío sin pantalla). `base.py` tiene lo compartido (`BaseWizard`, `EnviadaBase`, helpers).
- `automatizacion/tests/`: eventos y `congelada/` (la configuración congelada).
- `dashboard/tests/`: `panel/`, `equipo/`, `configuracion/` y `base.py` (`BasePanel`).
- `clients/tests/`: `modelos/`, `acceso/` y `operacion/`.

Un módulo de tests nuevo va en el paquete de su tema; lo que comparten varios módulos va en el `base.py` de la app, no se importa de otro módulo de tests. La base de test arranca vacía (los catálogos se cargan con `seed_catalogos`/`seed_modulos`, no con migraciones), así que cada test crea lo que necesita.

Al correr los tests `settings.py` cambia el hasher de contraseñas a uno rápido. El de producción (PBKDF2) es lento a propósito, y como cada test crea usuarios y se loguea, con él la suite tardaba más de 10 minutos en vez de segundos. Un test verifica que ese cambio nunca se active fuera de los tests.

## Variables de entorno (`.env`)

- `DJANGO_SECRET_KEY` — **obligatoria con `DJANGO_DEBUG=false`** (sin ella la app no arranca). `DJANGO_DEBUG` (default `false`; en dev ya viene en `true` por el `.env`).
- `DJANGO_ALLOWED_HOSTS` y `DJANGO_CSRF_TRUSTED_ORIGINS` (con `https://`) — el dominio real; sin ellos hay 400/403.
- `DJANGO_EMAIL_BACKEND` (usa el backend de consola en dev; en producción el SMTP — `EMAIL_HOST`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, etc. — va en un archivo aparte, `.env.mail`, que maneja deploy: ver `deploy/CORREO.md`)
- `IMPLEMENTATION_TEAM_EMAILS` — lista separada por comas que recibe el mail de resumen al completarse una implementación.
- `TRUSTED_PROXY_COUNT` — cuántos proxies reverso propios hay delante de la app (default `1` en producción, `0` en desarrollo). Lo usa el límite de intentos de login para saber la IP real del cliente.
- `SITE_BASE_URL` — usado para armar links absolutos en los mails cuando no hay `request` disponible.
- `MYSQL_DB`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST`, `MYSQL_PORT` — la base en producción. Si `MYSQL_DB` no está seteado, la app usa SQLite (desarrollo y tests).
- `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, `DJANGO_SUPERUSER_EMAIL` — opcionales; `manage.py ensure_superuser` crea ese superusuario si no existe (útil donde no hay shell).

## Producción

Motor de base de datos: **MySQL 8+** (`utf8mb4`, driver PyMySQL). Hay dos formas de desplegarlo, con la misma app:

- **Docker** (`deploy/DOCKER.md`): un contenedor con Gunicorn contra el MySQL existente. El CI (`.github/workflows/docker.yml`) corre el lint y los tests en cada push, y publica la imagen en `ghcr.io` solo cuando se crea un tag de versión (`vX.Y.Z`).
- **Directo sobre Ubuntu** (`deploy/sin-docker/README.md`): alternativa **no soportada y desactualizada** (systemd + nginx + MySQL). Usar Docker.

En ambos casos:

- `DJANGO_DEBUG=false` y las variables obligatorias de arriba (el contenedor valida que estén todas y avisa cuáles faltan).
- El proxy reverso (que pone el TLS) reenvía el dominio a Gunicorn conservando `Host` y `X-Forwarded-Proto`. Se pide un subdominio propio, separado del portal WordPress.
- Estáticos: los sirve la propia app (WhiteNoise, tras `collectstatic`); no hace falta configurarlos en el proxy.
- Adjuntos subidos (`MEDIA_ROOT`, `media/`): requieren un volumen/carpeta persistente y entrar en el backup. Los sirve la app con login (`/media/`): el equipo ve cualquiera y un cliente solo los suyos. **No publicar `/media/` desde el proxy.**
- Después de cada `migrate` hay que correr `seed_catalogos` y `seed_modulos` (idempotentes).
- **Límite de intentos de login** (django-axes): 5 fallos seguidos con el mismo usuario desde la misma IP bloquean ese par por 30 minutos, en `/login/` y `/admin/login/`. Requiere que el proxy reenvíe `X-Forwarded-For` (ver `deploy/DOCKER.md`). Para desbloquear a alguien: `manage.py axes_reset_username <usuario>`.
- SMTP real para los mails, en `.env.mail` (en dev se usa el backend de consola). Lo configura deploy: `deploy/CORREO.md`.

## Los pasos del wizard

1. Datos de contacto · 2. Módulos · 3. Sucursales (con Fichada) · 4. **Nómina** · 5. **Roles** (con Recibo Digital o Legajos) · 6. Configuración y adjuntos (con Recibo Digital) · 7. **Firma del recibo** (con Recibo Digital) · 8. Licencias y Novedades (con Novedades) · 9. Documentos de legajo (con Legajos) · 10. Revisión y envío.

La nómina va **antes** que los roles para poder elegir a las personas con rol de esa lista (cada fila de roles tiene un buscador «Buscar en la nómina» que completa nombre, CUIL y mail), y las sucursales antes que la nómina para asignar a cada empleado la suya. En la nómina se puede **editar** a cada empleado (botón «Editar»; también desde la ficha del panel). Los números de paso están definidos una sola vez, como constantes, en `onboarding/services.py`.

**Importar la nómina** (`.xlsx` o `.csv`, hasta 5.000 filas por archivo): se aceptan fechas reales de Excel o en texto (DD/MM/AAAA), CUIL con o sin guiones, y CSV de Excel en español (`;`, cp1252). Si el archivo no se puede leer, falta una columna obligatoria o es demasiado grande, se avisa con un mensaje claro y no se carga nada; las filas con error (CUIL inválido, fecha que no se entiende, valor demasiado largo, mail inválido) se informan con su número de fila y no impiden cargar las demás. La carga es todo-o-nada (una sola transacción) y en lote: 5.000 empleados tardan unos 4 segundos. Se avisa de las columnas desconocidas y de los «Reporta A / Aprobador» que no están en la nómina. **El archivo no se guarda** (tiene datos personales): solo queda el registro de la importación.

**Firma del recibo.** El cliente sube la imagen de la firma del apoderado y, sobre su modelo de recibo, arrastra y redimensiona tres recuadros (firma de la empresa, empleado en conformidad y en disconformidad). Solo se guarda su **intención** (página y recuadros como fracciones de la página, más la imagen con su `sha256`): el portal no la traduce a Napsis. El equipo la **valida**, la **observa** (motivos de un catálogo cerrado; devuelve el relevamiento al cliente con una ronda) o la **corrige** desde la ficha, y no se puede validar la documentación con la firma sin validar. Las imágenes subidas nunca se borran ni se pisan. El recibo se dibuja en el navegador con PDF.js; si no se pudiera mostrar, la firma se ubica con los campos numéricos.

**Seguimiento.** Una implementación **pendiente** a la que nadie le hizo nada en **7 días** se marca como **«Implementación sin movimiento»**: en el listado (con su estado real debajo, para saber dónde quedó trabada), en la ficha, en el filtro «Estado» y en el reporte (columnas «Última actividad» y «Sin movimiento»). No es un estado más: se deriva del último evento. Lo saca de ahí **cualquier acción** sobre la implementación (del cliente o del equipo), **un comentario** o **el envío de documentación**. El límite es `Implementacion.DIAS_SIN_MOVIMIENTO`. Cada implementación tiene además **comentarios del equipo**: notas internas que solo se agregan (no se editan ni se borran) y que el cliente nunca ve, ni en pantalla, ni en mails, ni en la configuración congelada.

**Configuración congelada.** Al validar la documentación se crea una `ConfiguracionCongelada` (en `automatizacion/`): un JSON con lo aprobado, usando códigos estables y no nombres editables, más una **copia inmutable de los archivos** (modelo de recibo, logo, banner y firma) con su `sha256`, guardada en `congeladas/<uuid>/v<N>/`. De la nómina solo van las cantidades (los datos personales ya los conserva la base). Es de solo lectura y cada validación crea una versión nueva; si el equipo cambia algo después, la validación se pierde y la versión anterior queda como historia. El equipo la ve y la descarga como `.json` desde la ficha; las copias de los archivos no las ve el cliente.

## Decisiones deliberadas

- **PDF.js viaja con el repositorio** (`static/vendor/pdfjs/`, ~1,4 MB) en lugar de cargarse desde un CDN. Es un peso a propósito: el cliente es corporativo y sus redes suelen bloquear dominios externos o exigir una lista de permitidos, y el editor de firma no puede quedar inutilizable por eso. La versión está fija (3.11.174, licencia Apache 2.0) y se actualiza a mano (`static/vendor/pdfjs/LEEME.md`).
- **Las tipografías también viajan con el repositorio** (`static/fonts/`, Montserrat y Roboto variables, subconjunto latino, ~80 KB, licencia OFL) en lugar de cargarse desde Google Fonts, por el mismo motivo: no hay ningún pedido a dominios externos. Hoy el portal no depende de ningún tercero en el navegador.

## Qué exige el wizard antes de poder enviar

El cliente no puede enviar el relevamiento hasta completar (el paso 10 lista lo que falta, con link a cada paso, y el botón queda deshabilitado; el servidor lo valida igual):

- **Razón social y CUIT** de la empresa (paso 1). El implementador puede cargarlos al crear la implementación; si no, los completa el cliente. Los CUIT se validan con su dígito verificador (acepta varios, separados por coma).
- **Roles** (paso 5; si hay Recibo Digital o Legajos): al menos un Apoderado/Firmante, un Liquidador y un Admin. de RRHH.
- **Modelo de recibo** en PDF (paso 6; si hay Recibo Digital).
- **Firma del recibo** (paso 7; si hay Recibo Digital): la imagen de la firma y su ubicación sobre el recibo.
- **Nómina** (paso 4): al menos un empleado.
- **Recibo Digital**: es obligatorio en toda implementación (no se puede desmarcar, ni el cliente ni el equipo).
- **Sucursales** (paso 3; si hay Fichada): al menos una con nombre.
- **Firma observada**: si el equipo la observó, el cliente tiene que ajustarla antes de volver a enviar.

**Validar y cumplir.** «Validar documentación» repite este mismo control y además exige la firma validada; la ficha muestra qué falta antes de apretar el botón. Solo se puede marcar como **cumplida** una implementación ya validada. Si después de validar el equipo cambia algo de lo que se va a configurar (datos, módulos, roles, sucursales, liquidaciones, firma, nómina…), la validación **se pierde** y vuelve a «Documentación completa - Pendiente de validación» (queda el evento `estado.validacion_revocada`); cambiar solo la fecha de implementación no la invalida.

**Condiciones del proceso.** Al crear la implementación (y después desde su ficha) el equipo decide qué deja fijo y qué decide el cliente. Cada dato se bloquea **al completarlo**; si se deja vacío, lo decide el cliente:

- **Tipo de firma** (electrónica o digital) y **nomenclatura de los recibos PDF**: si el implementador los define, el cliente los ve en el paso 6 pero no los puede cambiar (ni editando el formulario a mano).
- **Solo Área única**: bloquea la segmentación del liquidador.
- **Máximo de personas con rol** (de 3 a 6): cuántas filas ve el cliente en el paso de roles. El mínimo es 3 porque tiene que cargar un Apoderado/Firmante, un Liquidador y un Admin. de RRHH.

En el alta del panel estas condiciones están plegadas bajo **Opciones avanzadas**. El tipo de empresa (ART o comercial) no está: se agrega cuando se defina qué cambia en el proceso.

**Fecha de implementación.** En el paso 10 el cliente puede pedir una fecha (es opcional), pero no antes de **10 días hábiles** desde hoy (lunes a viernes; no se descuentan feriados). Si el equipo ya había puesto una fecha, esa se respeta tal cual. El equipo de implementación puede poner cualquier fecha desde el panel, sin ese mínimo.

Cada implementación tiene un **implementador asignado** (por defecto quien la crea, se elige en el alta y se puede reasignar). Es quien lleva la implementación y, además de la lista `IMPLEMENTATION_TEAM_EMAILS`, recibe sus notificaciones.

## Reporte exportable

Al pie del panel (`/panel/`), el botón **Exportar (.xlsx)** descarga todas las implementaciones, sin filtros: empresa, razón social, CUIT(s), estado, paso actual, implementador asignado, quién la creó, mail y teléfono de contacto, fecha de solicitud, de envío del cliente y de implementación (real si está cumplida, estimada si no), módulos, cantidad de empleados y sucursales, y si hay un pedido de contacto sin atender. Los textos que parecen fórmulas (`=...`) se escriben como texto para que no se ejecuten al abrir el archivo en Excel (lo mismo en la nómina descargable).

## Seguridad y operación (producción)

- **HTTPS obligatorio:** la app redirige a https, marca las cookies como `Secure` y manda HSTS (apagable solo para un ensayo con `DJANGO_FORCE_HTTPS=false`). El proxy tiene que mandar `X-Forwarded-Proto`. Ver `deploy/DOCKER.md`.
- **Valores de ejemplo:** el contenedor no arranca si la clave secreta es de ejemplo o corta, o si las contraseñas siguen en `cambiar`; el superusuario inicial pasa por los validadores de contraseña.
- **Recuperar contraseña:** el mismo mail no puede pedir el link más de una vez cada 10 minutos (y una IP tiene un tope general), con la misma respuesta siempre para no revelar qué cuentas existen. Usa una caché en archivos compartida entre los workers.
- **Errores 500:** quedan en `logs/errores.log` (en Docker, volumen `napsis_logs`; con fecha y traceback, rota a los 5 MB). El aviso por mail existe pero está **apagado**: se activa definiendo `ERROR_ALERT_EMAILS`.
- **`/salud/`:** responde 200 si la app llega a la base; lo usa el healthcheck del contenedor.
- **Catálogos:** `seed_catalogos` y `seed_modulos` corren en cada arranque pero solo cargan lo que falta o está vacío: lo que se corrija desde el admin no se duplica ni se revierte (`seed_catalogos --completar` agrega lo que falte de la lista original).
- **Versiones fijas** en `requirements.txt`, y el CI corre `makemigrations --check` y la suite en SQLite **y en MySQL 8** antes de publicar la imagen.
- **Cómo desplegar, actualizar y volver atrás:** `deploy/RELEASE.md`.

## Mails

**Al equipo** (`IMPLEMENTATION_TEAM_EMAILS` + el implementador asignado): resumen cuando el cliente envía su relevamiento, y pedido de contacto.

**Al cliente:**
- *Invitación*: si en el alta se carga el **mail del cliente**, la cuenta nace sin contraseña y le llega un link para crearla (vale 7 días, se usa una sola vez). Sin mail, la contraseña se genera y el implementador la ve una única vez, como antes. Desde la ficha se puede reenviar el link ("Enviar mail para crear contraseña"); no cambia la contraseña actual hasta que el cliente lo use.
- *Olvidé mi contraseña*: en el login, `/clave/olvide/`. Funciona con el mail guardado en la cuenta.
- *Confirmaciones*: "Recibimos tu información" al enviar el relevamiento y "Tu implementación está lista" al marcarla cumplida. Van al mail de contacto de la implementación o, si no tiene, al de la cuenta; si no hay ninguno, no se manda nada.

Un mail que falla (SMTP caído) nunca rompe el flujo: queda en el log y, en el panel, se avisa para reenviarlo a mano.

## Cómo probar el flujo completo

1. Entrar a `/panel/`, loguearse, crear una implementación (elegís un Cliente existente o cargás uno nuevo con Nombre + CUIT(s); esto genera el link único).
2. Abrir el link generado en una pestaña sin sesión (simula al cliente) y completar los 9 pasos.
3. En el paso de empleados, se puede descargar la plantilla vacía, completarla y subirla, o cargar empleados a mano.
4. Al enviar el paso 9, la implementación queda "Pendiente - Completo por cliente" (el cliente ya cargó todo; sigue pendiente porque el trabajo de implementar es del equipo), se disparan los mails (visibles en consola en dev). Pasa a "Cumplida" recién cuando el equipo la marca como cumplida desde el panel.
5. Con el mismo link, el cliente puede volver a entrar y ver todo en solo lectura, y pedir que lo contacten ("Pedir que me contacten") — eso también manda un mail al equipo.
6. Desde `/panel/`, en la ficha de la implementación, se puede reiniciar el link, anular la implementación (pasa a "Cancelada" y el cliente ya no puede completarla), y marcar como atendido un pedido de contacto.
