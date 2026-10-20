# Documentación

Todo lo necesario para entender el código sin leerlo línea por línea. Está organizada de lo general a lo particular:

| Quiero… | Leo |
|---|---|
| Entender de qué se trata y cómo se organiza | [`arquitectura.md`](arquitectura.md): capas, apps, modelo de datos, pasos del wizard, estados, recorrido completo, despliegue |
| Saber **qué puedo llamar** desde afuera (API, agente, comando) | [`operaciones-publicas.md`](operaciones-publicas.md): la lista corta de operaciones públicas, con firma, efectos y eventos |
| Entender **por qué el sistema se comporta así** | [`flujos-de-negocio.md`](flujos-de-negocio.md): la lógica de negocio con diagramas de flujo |
| Ver las **tablas y sus relaciones** (DER) | [`base-de-datos.md`](base-de-datos.md): diagrama entidad-relación de las 25 tablas, qué pasa al borrar (`on_delete`) y las restricciones de unicidad |
| Encontrar **dónde está** cada función y qué hace | [`modulos/`](modulos/): cada app dividida en componentes y funciones |
| Publicar una versión o volver atrás | [`../deploy/RELEASE.md`](../deploy/RELEASE.md) |
| Configurar el correo o Docker | [`../deploy/CORREO.md`](../deploy/CORREO.md), [`../deploy/DOCKER.md`](../deploy/DOCKER.md) |
| Correr los tests | sección *Tests* del [`README`](../README.md) |

## Los módulos

| App | Qué hace | Documento |
|---|---|---|
| `onboarding` | El wizard del cliente, las acciones (crear, enviar, validar, devolver, cumplir) y los servicios de guardado | [`modulos/onboarding.md`](modulos/onboarding.md) |
| `clients`, `catalog` | Los modelos centrales (cliente, implementación, firma, rondas, comentarios) y los catálogos con códigos estables | [`modulos/clients-y-catalog.md`](modulos/clients-y-catalog.md) |
| `employees`, `notifications` | La nómina y su importación; los mails | [`modulos/employees-y-notifications.md`](modulos/employees-y-notifications.md) |
| `automatizacion`, `dashboard` | Actores, eventos y configuración congelada; el panel del equipo | [`modulos/automatizacion-y-dashboard.md`](modulos/automatizacion-y-dashboard.md) |

## Cómo se ven los diagramas

Los diagramas están escritos en [Mermaid](https://mermaid.js.org/). GitHub los dibuja directamente. En VS Code se ven con la extensión *Markdown Preview Mermaid Support*.

## Cómo mantener esta documentación al día

La documentación describe el código, así que cambia con él. Cuando toques algo:

- **Agregaste, renombraste o quitaste una operación pública** (una función de `onboarding/acciones.py`, de `onboarding/services/` o de `automatizacion/`): actualizá `operaciones-publicas.md`.
- **Cambiaste una regla de negocio** (qué falta para enviar o validar, un estado, un mail): actualizá `flujos-de-negocio.md` y, si cambia el recorrido general, `arquitectura.md`.
- **Agregaste, moviste o renombraste una función o un archivo:** actualizá el documento de su módulo en `modulos/`.
- **Agregaste un evento:** sumalo al catálogo de `operaciones-publicas.md` y a la tabla de `arquitectura.md`.

Los tests son la otra mitad de la documentación: están agrupados por tema en cada app y muestran cómo se usa cada operación (`onboarding/tests/acciones/`, `onboarding/tests/revision/`, …).

> `docs/plan-automatizacion.md` es un borrador de trabajo que queda solo en el equipo local (no se sube al repositorio); este índice no depende de él.
