# Correo saliente (SMTP) — guía para deploy

La app manda mails por SMTP. **Toda su configuración vive en un archivo propio, `.env.mail`**,
separado de `.env.docker`, para que la maneje quien despliega sin tocar el resto. El código no
necesita cambios: se lee de variables de entorno al arrancar.

```bash
cp .env.mail.example .env.mail      # completar y listo
docker compose up -d                # o `docker compose restart` si ya estaba corriendo
```

`docker-compose.yml` carga `.env.mail` como segundo `env_file`, **opcional** (requiere Docker
Compose >= 2.24). Si no existe, la app arranca igual pero **no envía mails**: los imprime en el
log y el arranque lo avisa con una `ADVERTENCIA`.

## Qué manda la app

| Mail | A quién | Cuándo |
|---|---|---|
| Invitación para crear contraseña | Cliente | Al crear la implementación con "Mail del cliente", o al reenviarla desde la ficha |
| Recuperar contraseña | Cliente / equipo | Desde "¿Olvidaste tu contraseña?" en el login |
| Recibimos tu información | Cliente | Cuando envía el relevamiento |
| Tu implementación está lista | Cliente | Cuando el equipo la marca cumplida |
| Resumen de implementación | Equipo (`IMPLEMENTATION_TEAM_EMAILS`) + implementador asignado | Cuando el cliente envía |
| Pedido de contacto | Equipo + implementador asignado | Cuando el cliente pide que lo contacten |

Todos son texto plano. Un mail que falla **no rompe el flujo** (queda en el log y, en el panel,
se avisa para reenviarlo a mano).

## Variables (`.env.mail`)

| Variable | Default | Para qué |
|---|---|---|
| `DJANGO_EMAIL_BACKEND` | consola | `django.core.mail.backends.smtp.EmailBackend` para enviar de verdad |
| `EMAIL_HOST` / `EMAIL_PORT` | — / 587 | Servidor SMTP |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | vacíos | Credenciales. Vacías si el servidor autoriza por IP (relay) |
| `EMAIL_USE_TLS` | `true` | STARTTLS (puerto 587) |
| `EMAIL_USE_SSL` | `false` | SSL implícito (puerto 465). No combinar con TLS |
| `EMAIL_TIMEOUT` | `10` | Segundos de espera antes de rendirse (evita colgar un worker) |
| `DEFAULT_FROM_EMAIL` | `portal@napsislatam.com` | Remitente de todos los mails |

Quién recibe los avisos internos (`IMPLEMENTATION_TEAM_EMAILS`) y los links absolutos de los mails
(`SITE_BASE_URL`) siguen en `.env.docker`: no son del servidor SMTP. **`SITE_BASE_URL` tiene que
ser la URL pública real**: de ahí salen los links de "crear contraseña".

## Si la cuenta es de Outlook / Microsoft 365

La app solo sabe autenticarse con **usuario y contraseña** (SMTP AUTH básico). Microsoft viene
retirando ese método para el envío en Microsoft 365, así que hay que confirmar qué permite el
tenant de Napsis antes de lanzar. Opciones, de más a menos simple para esta app:

1. **Conector de relay SMTP en Exchange Online autorizado por IP.** Sin usuario ni contraseña
   (`EMAIL_HOST_USER`/`EMAIL_HOST_PASSWORD` vacíos); necesita IP de salida fija. Funciona sin tocar código.
2. **SMTP AUTH habilitado en el buzón** que envía (`smtp.office365.com`, 587, STARTTLS), si el
   tenant todavía lo permite y el buzón no exige MFA para ese acceso.
3. **Un proveedor transaccional** (SES, SendGrid, etc.) con el dominio verificado.
4. **Microsoft Graph (OAuth2).** La app no lo soporta hoy; habría que escribir un backend de mail.

Aparte: `DEFAULT_FROM_EMAIL` tiene que ser la casilla autenticada o una con permiso "Enviar como",
y el dominio debe tener **SPF y DKIM** (idealmente DMARC) para que las invitaciones no caigan en spam.

## Cómo probar que funciona

Con la app corriendo, mandá un mail de prueba desde el contenedor (cambiá el destino):

```bash
docker compose exec app python manage.py shell -c "from django.core.mail import send_mail; print(send_mail('Prueba del portal', 'Si te llegó, el SMTP funciona.', None, ['tu-casilla@napsislatam.com']))"
```

Imprime `1` si el servidor aceptó el mail; si falla, muestra el error del SMTP (credenciales,
TLS, remitente rechazado, timeout). Después, la prueba real: crear una implementación con tu
propio mail como "Mail del cliente" y ver que llega la invitación y que el link abre la página
para crear la contraseña.
