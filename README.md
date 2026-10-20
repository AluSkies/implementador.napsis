# Portal de Implementación Napsis

Webapp Django para el relevamiento de autoservicio de nuevos clientes de Napsis. Reemplaza los 5 Excel de relevamiento (Datos de Nómina, Documentos Legajo Digital, Importación de Nómina, Información Pre Implementación, Licencias y Novedades) por un **wizard web de 10 pasos con link único por cliente**, y le da al equipo de implementación un **panel** para seguir, validar y trabajar cada caso.

**Alcance de esta versión (1.0).** El portal es una herramienta de **estado, control y trabajo del equipo de implementación**: no se integra con Napsis. Configurar en Napsis sigue siendo trabajo manual del equipo, fuera del portal. Lo que el portal sí hace es relevar, ordenar, validar y dejar una **configuración congelada** (la foto inmutable de lo aprobado) para que quien configure tenga una única fuente de verdad.

**Contenido**

1. [Documentación del código](#documentación-del-código)
2. [Quién usa qué: roles y permisos](#quién-usa-qué-roles-y-permisos)
3. [Puesta en marcha en desarrollo](#puesta-en-marcha-en-desarrollo)
4. [Despliegue en producción (para infraestructura)](#despliegue-en-producción-para-infraestructura)
5. [Variables de entorno y cómo pasar la clave secreta](#variables-de-entorno-y-cómo-pasar-la-clave-secreta)
6. [Cómo está armado el proyecto](#cómo-está-armado-el-proyecto)
7. [El wizard del cliente](#el-wizard-del-cliente)
8. [El panel del equipo](#el-panel-del-equipo)
9. [Reglas de negocio importantes](#reglas-de-negocio-importantes)
10. [Seguridad y operación](#seguridad-y-operación)
11. [Mails](#mails)
12. [Tests](#tests)
13. [Decisiones deliberadas](#decisiones-deliberadas)
14. [Cómo probar el flujo completo a mano](#cómo-probar-el-flujo-completo-a-mano)

---

## Documentación del código

Para entender el código está el apartado [`docs/`](docs/README.md): la [arquitectura](docs/arquitectura.md) con diagramas, la lista corta de [operaciones públicas](docs/operaciones-publicas.md) (el contrato para integrar), la [lógica de negocio](docs/flujos-de-negocio.md) con diagramas de flujo y cada [módulo en sus componentes y funciones](docs/modulos/). Además, los tests agrupados por tema muestran cómo se usa cada operación.

Para quien despliega: [`deploy/RELEASE.md`](deploy/RELEASE.md) (primera vez, actualizar y volver atrás), [`deploy/DOCKER.md`](deploy/DOCKER.md) (variables, proxy, HTTPS) y [`deploy/CORREO.md`](deploy/CORREO.md) (SMTP).

---

## Quién usa qué: roles y permisos

| Rol | Cuenta | Ve | Actúa sobre | Asigna implementaciones |
|---|---|---|---|---|
| **Cliente** | sin `is_staff` | solo las suyas, por el wizard | sus propias respuestas | no |
| **Implementador** | staff (sin ser superusuario) | **todas** las implementaciones | **solo las que tiene asignadas** | no |
| **Supervisor** | staff del grupo `Supervisor` | todas | **todas** | sí |
| **Admin** | superusuario | todas | todas | sí, y además administra las cuentas del equipo |

- Un implementador que abre una implementación ajena la ve en **solo lectura** (sin formularios y con un aviso); si arma el pedido a mano, el servidor responde 403. Ver, descargar la nómina y exportar el reporte es para todo el equipo.
- Al crear una implementación, un implementador se la asigna a sí mismo; el supervisor y el admin eligen a quién. Reasignar es solo de ellos.
- Las implementaciones sin asignar solo las puede tocar un supervisor o un admin.
- La regla vive en un único lugar: `dashboard/permisos.py` (`puede_asignar`, `puede_accionar`, `puede_accionar_sobre_el_cliente`).
- **Cuentas del equipo:** el primer Admin se crea con `createsuperuser` (o, donde no hay shell, con `ensure_superuser` y las variables `DJANGO_SUPERUSER_*`). Después el Admin crea las demás desde el panel (`/panel/implementadores/`), eligiendo si son Implementador o Supervisor; también puede cambiarles el rol. La contraseña se genera sola y se muestra una única vez. La baja es lógica (la cuenta no ingresa pero se conserva, para no perder a quién se atribuyen las implementaciones que creó).
- Los eventos registran el tipo de actor (`cliente`, `implementador`, `supervisor`, `admin`, `sistema`, `servicio`, `agente`).

---

## Puesta en marcha en desarrollo

Requisitos: Python 3.12. En desarrollo se usa SQLite; no hace falta instalar nada más.

```bash
python -m venv venv
venv/Scripts/pip install -r requirements.txt        # en Linux/macOS: venv/bin/pip
cp .env.example .env                                # completar (ver más abajo)
venv/Scripts/python manage.py migrate
venv/Scripts/python manage.py seed_catalogos        # catálogos: licencias, novedades, documentos
venv/Scripts/python manage.py seed_modulos          # módulos contratables
venv/Scripts/python manage.py createsuperuser
venv/Scripts/python manage.py runserver
```

- Panel interno: `http://localhost:8000/panel/` (requiere login).
- Wizard de cliente: se accede por el link único que genera el panel (`/r/<token>/`); el cliente además tiene un usuario y contraseña para volver a entrar.
- `seed_catalogos` y `seed_modulos` **no son datos de demo**: cargan los catálogos reales que el portal necesita para funcionar (son idempotentes y el contenedor los corre en cada arranque).
- El repositorio **no trae datos de demostración**: la base de desarrollo arranca vacía y los clientes se crean desde el panel.

---

## Despliegue en producción (para infraestructura)

Motor de base de datos: **MySQL 8+** (`utf8mb4`, driver PyMySQL). La app se entrega como **una imagen de Docker** (un contenedor con Gunicorn) que se conecta al MySQL existente de Napsis: no incluye ni levanta una base propia.

**Lo que el equipo de infra necesita está en el repositorio:**

| Archivo | Qué es |
|---|---|
| [`Dockerfile`](Dockerfile) | Construye la imagen (Python 3.12, dependencias fijas, `collectstatic` en el build, usuario sin privilegios). |
| [`docker-compose.yml`](docker-compose.yml) | Un servicio `app`, puerto solo en `127.0.0.1:8000`, volúmenes `napsis_media` y `napsis_logs`, healthcheck. |
| [`docker/entrypoint.sh`](docker/entrypoint.sh) | Valida la configuración, aplica migraciones, carga catálogos y crea el superusuario inicial. |
| [`.env.docker.example`](.env.docker.example) | Plantilla de la configuración (se copia a `.env.docker`, que **nunca** se sube). |
| [`.env.mail.example`](.env.mail.example) | Plantilla del correo saliente (SMTP), opcional. |
| [`.github/workflows/docker.yml`](.github/workflows/docker.yml) | CI: lint, migraciones al día y la suite completa en SQLite **y en MySQL 8**; publica la imagen en `ghcr.io` **solo al crear un tag `vX.Y.Z`**. |
| [`deploy/RELEASE.md`](deploy/RELEASE.md) | Guía paso a paso: primer despliegue, actualizar y volver atrás. |

**Resumen:**

```bash
cp .env.docker.example .env.docker       # completar: clave secreta, dominio, MySQL, superusuario
cp .env.mail.example .env.mail           # cuando se tenga el SMTP (opcional)
echo "NAPSIS_IMAGE=ghcr.io/aluskies/implementador-napsis:v1.0.0" > .env
docker login ghcr.io
docker compose pull && docker compose up -d
docker compose logs -f app
```

Lo que hay que saber:

- **Proxy y TLS:** el proxy reverso de Napsis recibe el tráfico público y reenvía el subdominio a `127.0.0.1:8000`, conservando `Host`, `X-Forwarded-For` y `X-Forwarded-Proto: https`. La app **exige HTTPS por sí misma** (redirige, cookies `Secure`, HSTS): sin ese header entra en bucle. Ejemplo de configuración en `deploy/DOCKER.md`. Se pide un subdominio propio, separado del portal WordPress.
- **Estáticos:** los sirve la propia app (WhiteNoise); no hay que configurarlos en el proxy.
- **Adjuntos** (`/app/media`, volumen `napsis_media`): **tienen que entrar en el backup** junto con el MySQL. Los sirve la app con login (el equipo ve cualquiera; un cliente solo los suyos): **no publicar `/media/` desde el proxy**.
- **Base de datos:** el usuario de MySQL necesita permisos de esquema (`CREATE/ALTER/DROP/INDEX` además del CRUD) para las migraciones.
- **Versiones:** cada versión es una imagen con tag (`v1.0.0`). Los datos viven en MySQL y en el volumen de adjuntos, así que se puede actualizar o volver atrás sin perderlos, **siempre que haya backup**.
- **No hay datos de demostración ni semillas de prueba en la imagen:** solo los catálogos reales (`seed_catalogos`, `seed_modulos`). `.dockerignore` deja afuera `.env*`, `*.xlsx`, `referencias/`, la base local y los adjuntos.
- **Cuenta Admin:** se crea sola en el primer arranque con `DJANGO_SUPERUSER_USERNAME/PASSWORD/EMAIL` en `.env.docker`; si no se definieron, `docker compose exec app python manage.py createsuperuser`. Si no hay ningún Admin, el arranque lo advierte en el log. Detalle en [`deploy/DOCKER.md`](deploy/DOCKER.md#la-cuenta-admin-primer-ingreso).
- **Healthcheck:** `/salud/` responde 200 si la app llega a la base.
- **Alternativa sin Docker** (`deploy/sin-docker/`): no soportada y desactualizada. Usar Docker.

---

## Variables de entorno y cómo pasar la clave secreta

### `DJANGO_SECRET_KEY` (la clave secreta)

Firma las sesiones y los links de «crear/recuperar contraseña». Si alguien la conociera podría falsificarlos, por eso **no tiene valor por defecto** y la app **no arranca en producción sin ella**.

1. **Generarla** (en cualquier computadora con Python; hay que guardarla en el gestor de secretos de infra):

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(50))"
   ```

2. **Pasarla como variable de entorno**, nunca dentro del código ni de la imagen:
   - **Con `docker compose` (lo previsto):** en el archivo `.env.docker` del servidor, en una línea `DJANGO_SECRET_KEY=<la clave>` (sin comillas ni espacios). El compose lo carga con `env_file`.
   - **Con otro orquestador** (Kubernetes, Swarm, un secret manager): inyectarla como variable de entorno `DJANGO_SECRET_KEY` del contenedor (por ejemplo, desde un `Secret`).
   - **Prueba rápida con `docker run`:** `docker run -e DJANGO_SECRET_KEY="<la clave>" --env-file .env.docker ...`. Evitar pasarla por línea de comandos en servidores compartidos (queda en el historial); usar `--env-file`.
3. **Reglas que el contenedor controla al arrancar** (si no se cumplen, **no arranca** y dice cuál falló): que esté definida, que tenga **al menos 40 caracteres** y que no sea un valor de ejemplo (`cambiar`, `generar-una-clave…`, `django-insecure-…`).
4. **Cuidados:** no subirla a git (`.env.docker` está ignorado), no reutilizar la de otro entorno y mantenerla **estable** entre despliegues. Si se cambia, las sesiones abiertas y los links de contraseña pendientes dejan de valer (no se pierden datos).

La clave `solo-para-el-build` del `Dockerfile` y la de los tests del CI son descartables: solo sirven para que Django arranque durante el build o los tests, y el entrypoint las rechaza.

### Resto de variables

**Obligatorias en producción** (si falta alguna, el contenedor no arranca y lista cuáles):

| Variable | Para qué |
|---|---|
| `DJANGO_SECRET_KEY` | Ver arriba. |
| `DJANGO_ALLOWED_HOSTS` | Dominio(s) de la app. Sin esto, todo da 400. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | El mismo dominio **con** `https://`. Sin esto, el login falla con 403. |
| `SITE_BASE_URL` | URL pública, para los links que salen en los mails. |
| `MYSQL_DB`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_HOST` | La base. Si `MYSQL_DB` no está, la app usaría SQLite (solo desarrollo y tests): el contenedor lo impide. |

**Opcionales:**

| Variable | Para qué |
|---|---|
| `DJANGO_DEBUG` | Por defecto `false`. **Debe quedar en `false` en producción.** |
| `MYSQL_PORT` | Puerto de MySQL (3306 por defecto). |
| `DJANGO_SUPERUSER_USERNAME/PASSWORD/EMAIL` | Crea el primer Admin al arrancar si no existe (contraseña real: mín. 8 caracteres, no común). Se puede borrar del archivo después. |
| `IMPLEMENTATION_TEAM_EMAILS` | Lista separada por comas que recibe el resumen cuando un cliente envía su relevamiento. |
| `TRUSTED_PROXY_COUNT` | Cuántos proxies propios hay delante (por defecto `1` en producción). Lo usa el límite de intentos de login para saber la IP real. |
| `DJANGO_FORCE_HTTPS`, `SECURE_HSTS_SECONDS` | HTTPS obligatorio (por defecto sí) y duración de HSTS (3600 s al principio; subir a un año cuando todo ande). |
| `ERROR_ALERT_EMAILS` | Quién recibe aviso por mail de los errores 500 (apagado por defecto). |
| `RUN_MIGRATIONS` | `1` por defecto. Con varias réplicas, `0` en todas y correr los pasos de base una vez como job aparte. |
| `LOG_DIR` | Carpeta del log de errores. |

**Correo saliente** (`.env.mail`, lo maneja deploy; ver [`deploy/CORREO.md`](deploy/CORREO.md)): `DJANGO_EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`/`EMAIL_USE_SSL`, `DEFAULT_FROM_EMAIL`. Sin SMTP la app funciona pero los mails solo se imprimen en el log.

En desarrollo alcanza con copiar `.env.example` a `.env` (trae `DJANGO_DEBUG=true`, y con `DEBUG` la app tolera una clave de relleno).

---

## Cómo está armado el proyecto

Todo es un monolito Django renderizado en el servidor. La lógica de negocio vive en **acciones y servicios que no dependen de `request`** (reciben un `Actor` y devuelven un `Resultado`), para poder invocarlas desde otras fuentes más adelante; las vistas solo traducen formularios a esas llamadas.

- `clients/` — `Cliente` (la empresa, persistente) e `Implementacion` (un proceso de relevamiento puntual, con su link único, estado, datos de contacto y configuración). De `Implementacion` cuelgan roles (`PersonaRol` y su **alcance**), sucursales, módulos, licencias, novedades, documentos y empleados: así una misma empresa puede repetir el proceso sin arrastrar datos de una ronda anterior. También el historial de versiones, las rondas de revisión y los comentarios internos.
- `automatizacion/` — actores, **registro de eventos que solo se agrega** y la **configuración congelada**.
- `onboarding/` — el wizard público, las acciones (alta, envío, validar, devolver, cumplir) y los servicios de guardado, partidos en un paquete (`onboarding/services/`: pasos, fechas, faltantes, secciones, roles, firma, nómina).
- `employees/` — empleados, importación de nómina (`.xlsx`/`.csv`), plantilla descargable y CUIL.
- `catalog/` — catálogos (tipos de licencia, de novedad, de liquidación y de documento con sus campos).
- `notifications/` — mails al equipo y al cliente.
- `dashboard/` — el panel interno: listado, ficha de la implementación, equipo, reporte y permisos.
- `templates/`, `static/` — plantillas y archivos estáticos (incluye PDF.js y las tipografías, ver [Decisiones deliberadas](#decisiones-deliberadas)).

---

## El wizard del cliente

Diez pasos; los condicionales dependen de los módulos contratados:

1. **Datos de contacto y de la empresa** · 2. **Módulos** · 3. **Sucursales** (con Fichada) · 4. **Nómina** · 5. **Roles** (con Recibo Digital o Legajos) · 6. **Configuración y adjuntos** (con Recibo Digital) · 7. **Firma del recibo** (con Recibo Digital) · 8. **Licencias y Novedades** (con Novedades) · 9. **Documentos de legajo** (con Legajos) · 10. **Revisión y envío**.

La nómina va **antes** que los roles para poder elegir de esa lista a las personas con rol, y las sucursales antes que la nómina para asignar a cada empleado la suya. Los números de paso están definidos una sola vez, como constantes, en `onboarding/services/pasos.py`.

- **Sucursales:** el paso explica en términos de Napsis Fichada para qué sirven; se muestra una tarjeta y un botón verde «Agregar sucursal» permite sumar todas las que hagan falta.
- **Nómina:** se importa un `.xlsx` o `.csv` (hasta 5.000 filas), se carga a mano o se edita empleado por empleado. Se descarga una **plantilla** con encabezados violeta (obligatorias) y azul (opcionales), ayudas en cada columna, listas desplegables y una hoja de instrucciones. Se aceptan fechas de Excel o en texto (DD/MM/AAAA), **CUIL con o sin guiones** (se guarda con los 11 dígitos y se muestra siempre como `NN-NNNNNNNN-N`) y CSV de Excel en español. Si el archivo no se puede leer o falta una columna obligatoria, no se carga nada; las filas con error se informan con su número y no impiden cargar las demás. La carga es todo-o-nada y en lote. **El archivo no se guarda** (tiene datos personales): solo queda el registro de la importación.
- **Roles:** al menos un Apoderado/Firmante, un Liquidador y un Admin. de RRHH. Apoderado y Liquidador tienen que estar en la nómina (hay un buscador que completa nombre, CUIL y mail). **Alcance del liquidador:** qué recibos ve se arma con dos listas cuya unión es el alcance: *grupos de la nómina* (todos los de un puesto, sector, gerencia, centro de costo o los supervisores) y *personas sueltas*. Sin nada cargado ve todos. Se guarda la regla y no la lista resultante, así que se recalcula si la nómina cambia. Si el equipo fijó «solo Área única», el editor no aparece.
- **Configuración y adjuntos:** tipo de firma, liquidador utilizado, nomenclatura, cápitas (se puede calcular como la suma de la nómina) y los tres archivos. Los archivos ya cargados se muestran con vista previa, **Quitar** (avisa y se puede deshacer) y **Reemplazar**; el modelo de recibo es obligatorio, así que solo se reemplaza. El banner y el logo se validan contra las medidas que acepta Napsis.
- **Firma del recibo:** el cliente sube la imagen de la firma y, sobre su modelo de recibo, arrastra y redimensiona tres recuadros (firma de la empresa, empleado en conformidad y en disconformidad). Solo se guarda su **intención** (página y recuadros como fracciones de la página, más la imagen con su `sha256`). El equipo la **valida**, la **observa** (motivos de un catálogo cerrado; devuelve el relevamiento con una ronda) o la **corrige**. Las imágenes subidas nunca se borran ni se pisan. El recibo se dibuja en el navegador con PDF.js; si no se pudiera mostrar, la firma se ubica con campos numéricos.
- **Revisión y envío:** lista lo que falta, con link a cada paso (el botón queda deshabilitado y el servidor lo valida igual). Permite pedir una **fecha de implementación** con un calendario que deja en gris, y no deja elegir, los primeros 10 días hábiles.
- Una vez enviado, el cliente vuelve a entrar con el mismo link y ve todo en solo lectura; puede pedir que lo contacten.

**Qué exige el wizard antes de poder enviar:** razón social y CUIT (con su dígito verificador; acepta varios separados por coma), Recibo Digital (obligatorio en toda implementación), al menos un empleado, los tres roles, el modelo de recibo en PDF y la firma (si hay Recibo Digital), una sucursal con nombre (si hay Fichada) y, si el equipo observó la firma, que el cliente la ajuste.

---

## El panel del equipo

- **Listado** (`/panel/`): filtros por cliente, estado y fecha; orden por columnas; alta de implementaciones en un modal.
  - **Cliente nuevo:** se carga nombre, razón social y CUIT (opcionales: si faltan, los completa el cliente), usuario y mail. Con mail el cliente recibe un link para crear su propia contraseña; sin mail, la contraseña se genera y se muestra una única vez.
  - **Cliente existente:** al elegirlo se completan solos los campos con lo que ya hay cargado (nombre y usuario no se editan; razón social, CUIT y mail se pueden corregir o completar). La implementación nueva hereda el teléfono y el mail de la última.
  - **Opciones avanzadas:** el equipo decide qué deja fijo y qué decide el cliente (tipo de firma, nomenclatura, «solo Área única», máximo de personas con rol de 3 a 6, módulos editables). Cada dato se bloquea al completarlo; si se deja vacío, lo decide el cliente.
- **Ficha de la implementación:** todas las secciones editables (según los permisos), con historial de versiones, firma, nómina, comentarios y la **configuración congelada**.
- **Equipo** (`/panel/implementadores/`, solo Admin): alta de cuentas, rol (Implementador o Supervisor), reinicio de contraseña, baja y reactivación.
- **Reporte exportable:** el botón «Exportar (.xlsx)» descarga todas las implementaciones (empresa, CUIT, estado, paso, implementador, fechas, módulos, cantidades, pedido de contacto sin atender, última actividad y «sin movimiento»). Los textos que parecen fórmulas se escriben como texto para que no se ejecuten en Excel.

---

## Reglas de negocio importantes

**Estados.** Una implementación está *pendiente*, *cumplida* o *cancelada*. Lo que se muestra se deriva además de si el cliente ya envió y de si el equipo validó: «A completar por el cliente», «Documentación completa - Pendiente de validación», «Validada», «Completo», «Cancelada», con la marca «Devuelta, ronda N» si se devolvió. No hay estados extra guardados.

**Validar, devolver y cumplir.** «Validar documentación» repite el control del envío y además exige la firma validada; la ficha muestra qué falta antes de apretar el botón. «Devolver al cliente» pide observaciones y abre una ronda de revisión. Solo se puede marcar como **cumplida** una implementación ya validada. Si después de validar el equipo cambia algo de lo que se va a configurar (datos, módulos, roles, sucursales, liquidaciones, firma, nómina…), **la validación se pierde** y vuelve a «Pendiente de validación» (queda el evento `estado.validacion_revocada`); cambiar solo la fecha de implementación no la invalida.

**Configuración congelada.** Al validar se crea una `ConfiguracionCongelada` (en `automatizacion/`): un JSON con lo aprobado, usando códigos estables y no nombres editables, más una **copia inmutable de los archivos** (modelo de recibo, logo, banner y firma) con su `sha256`, guardada en `congeladas/<uuid>/v<N>/`. De la nómina solo van las cantidades. Es de solo lectura y cada validación crea una versión nueva; si el equipo cambia algo, la validación se pierde y la versión anterior queda como historia. El equipo la ve y la descarga como `.json` desde la ficha; el cliente no ve las copias.

**Seguimiento: «Implementación sin movimiento».** Una implementación **pendiente** a la que nadie le hizo nada en **7 días** (`Implementacion.DIAS_SIN_MOVIMIENTO`) se marca así: en el listado (con su estado real debajo), en la ficha, en el filtro «Estado» y en el reporte. No es un estado más: se deriva del último evento. Lo saca de ahí cualquier acción, un comentario o el envío de documentación. Cada implementación tiene además **comentarios del equipo**: notas internas que solo se agregan (no se editan ni se borran) y que el cliente nunca ve, ni en pantalla, ni en mails, ni en la configuración congelada.

**Fecha de implementación.** El cliente puede pedir una fecha (opcional) pero **no durante los primeros 10 días hábiles** desde hoy (lunes a viernes; no se descuentan feriados): el primer día elegible es el día hábil 11. Si el equipo ya había puesto una fecha, se respeta tal cual; el equipo puede poner cualquiera desde el panel.

**Implementador asignado.** Cada implementación tiene uno (por defecto quien la crea). Es quien actúa sobre ella y, además de la lista `IMPLEMENTATION_TEAM_EMAILS`, recibe sus notificaciones.

---

## Seguridad y operación

- **HTTPS obligatorio:** redirige a https, cookies `Secure` y HSTS (apagable solo para un ensayo con `DJANGO_FORCE_HTTPS=false`). El proxy tiene que mandar `X-Forwarded-Proto`.
- **Valores de ejemplo:** el contenedor no arranca si la clave secreta es de ejemplo o corta, o si las contraseñas siguen en `cambiar`; el superusuario inicial pasa por los validadores de contraseña.
- **Límite de intentos de login** (django-axes): 5 fallos seguidos con el mismo usuario desde la misma IP bloquean ese par por 30 minutos, en `/login/` y `/admin/login/` (requiere `X-Forwarded-For`). Para desbloquear: `manage.py axes_reset_username <usuario>`.
- **Recuperar contraseña:** el mismo mail no puede pedir el link más de una vez cada 10 minutos (y una IP tiene un tope general), con la misma respuesta siempre para no revelar qué cuentas existen. Si la contraseña nueva es rechazada, el motivo se muestra en un recuadro aparte de las reglas.
- **Permisos por asignación:** ver [Quién usa qué](#quién-usa-qué-roles-y-permisos). Los adjuntos solo se sirven con login y a su dueño.
- **Errores 500:** quedan en `logs/errores.log` (en Docker, volumen `napsis_logs`; rota a los 5 MB). El aviso por mail está apagado hasta definir `ERROR_ALERT_EMAILS`.
- **Catálogos:** `seed_catalogos` y `seed_modulos` solo cargan lo que falta: lo que se corrija desde el admin no se duplica ni se revierte (`seed_catalogos --completar` agrega lo que falte de la lista original).
- **Versiones fijas** en `requirements.txt`; el CI corre `ruff`, `makemigrations --check` y la suite en SQLite y en MySQL 8 antes de publicar la imagen.

---

## Mails

**Al equipo** (`IMPLEMENTATION_TEAM_EMAILS` + el implementador asignado): resumen cuando el cliente envía su relevamiento, y pedido de contacto.

**Al cliente:**
- *Invitación*: si en el alta se carga el mail, la cuenta nace sin contraseña y le llega un link para crearla (vale 7 días, se usa una sola vez). Desde la ficha se puede reenviar («Enviar mail para crear contraseña»); no cambia la contraseña actual hasta que el cliente lo use.
- *Olvidé mi contraseña*: `/clave/olvide/`, con el mail guardado en la cuenta.
- *Confirmaciones*: «Recibimos tu información» al enviar y «Tu implementación está lista» al marcarla cumplida. Van al mail de contacto de la implementación o, si no tiene, al de la cuenta.

Un mail que falla (SMTP caído) nunca rompe el flujo: queda en el log y, en el panel, se avisa para reenviarlo a mano.

---

## Tests

```bash
venv/Scripts/python manage.py test                   # toda la suite (~890 tests, ~45 s)
venv/Scripts/python manage.py test --parallel        # en paralelo (~30 s)
venv/Scripts/python manage.py test onboarding        # una app
venv/Scripts/python manage.py test onboarding.tests.firma                  # un paquete
venv/Scripts/python manage.py test onboarding.tests.firma.test_servicio    # un módulo
venv/Scripts/python manage.py test --durations=10    # los 10 más lentos
venv/Scripts/python -m ruff check .                  # lint (lo mismo que corre el CI)
```

Si en el modo paralelo aparece `cannot pickle 'traceback' object`, es un test que falla escondido: correr sin `--parallel` para ver cuál.

**Contra MySQL** (como producción), con un contenedor descartable:

```bash
docker run -d --name napsis-mysql-test -e MYSQL_ROOT_PASSWORD=root -e MYSQL_DATABASE=napsis -p 127.0.0.1:3307:3306 mysql:8.4
MYSQL_DB=napsis MYSQL_USER=root MYSQL_PASSWORD=root MYSQL_HOST=127.0.0.1 MYSQL_PORT=3307 venv/Scripts/python manage.py test --noinput
docker rm -f napsis-mysql-test
```

(Se publica solo en `127.0.0.1` y se borra al terminar. Contra MySQL el modo `--parallel` necesita `mysqldump` instalado.)

**Dónde está cada cosa.** Hay tests por app, en paquetes `tests/` agrupados por tema para correr solo lo que se tocó: `onboarding/tests/` (`wizard/`, `firma/`, `revision/`, `liquidaciones/`, `imagenes/`, `formularios/`, `servicios/`, `acciones/`), `automatizacion/tests/` (eventos y `congelada/`), `dashboard/tests/` (`panel/`, `equipo/`, `configuracion/`) y `clients/tests/` (`modelos/`, `acceso/`, `operacion/`). Lo compartido va en el `base.py` de cada app. La base de test arranca vacía (los catálogos se cargan con `seed_catalogos`/`seed_modulos`, no con migraciones), así que cada test crea lo que necesita. En los tests del panel, `crear_supervisor` crea una cuenta que actúa sobre todo; lo que depende de la asignación se prueba en `dashboard/tests/equipo/test_permisos_por_asignacion.py`.

Al correr los tests `settings.py` cambia el hasher de contraseñas a uno rápido (el de producción, PBKDF2, es lento a propósito); un test verifica que ese cambio nunca se active fuera de los tests.

---

## Decisiones deliberadas

- **PDF.js viaja con el repositorio** (`static/vendor/pdfjs/`, ~1,4 MB) en lugar de cargarse desde un CDN. Es un peso a propósito: el cliente es corporativo y sus redes suelen bloquear dominios externos o exigir una lista de permitidos, y el editor de firma no puede quedar inutilizable por eso. La versión está fija (3.11.174, licencia Apache 2.0) y se actualiza a mano (`static/vendor/pdfjs/LEEME.md`).
- **Las tipografías también viajan con el repositorio** (`static/fonts/`, Montserrat y Roboto variables, subconjunto latino, ~80 KB, licencia OFL) en lugar de cargarse desde Google Fonts, por el mismo motivo. Hoy el portal no depende de ningún tercero en el navegador.
- **Sin integración con Napsis en esta versión:** quedan fuera la generación del archivo de carga, la cola de tareas, la evaluación de automatizabilidad y la integración con CRM. Las operaciones públicas de `docs/operaciones-publicas.md` están pensadas para sumarlas sin reescribir la lógica.
- **El alcance del liquidador es del portal, no de Napsis:** se relevan y validan las reglas, pero su configuración en Napsis es manual. El campo de texto `segmentacion_liquidador` convive con el alcance estructurado.
- **Los datos de demostración no se versionan:** el comando local de demo y sus datos ficticios están excluidos del repositorio y de la imagen.

---

## Cómo probar el flujo completo a mano

1. Entrar a `/panel/`, loguearse y crear una implementación (cliente existente o nuevo); esto genera el link único y, si se cargó mail, manda la invitación.
2. Abrir el link en una ventana sin sesión (simula al cliente) y completar los pasos. En el paso de empleados se puede descargar la plantilla, completarla y subirla, o cargar a mano.
3. Al enviar, la implementación queda «Documentación completa - Pendiente de validación» y se disparan los mails (en desarrollo, en la consola).
4. En la ficha del panel: validar la firma, **validar la documentación** (se crea la configuración congelada) y, cuando el equipo termine de configurar en Napsis, **marcarla como cumplida**. También se puede devolver al cliente con observaciones, agregar comentarios, reasignar (supervisor o admin) o anular.
5. El cliente puede volver a entrar con el mismo link y ver todo en solo lectura, y pedir que lo contacten (eso manda un mail al equipo).
