"""Quién hace cada cosa.

Toda acción sobre una implementación tiene un actor: una persona (cliente, implementador, admin),
el propio sistema, o a futuro un servicio externo (el CRM) o un agente. Se usa un objeto en lugar de
textos sueltos ("Cliente", el nombre de usuario...) para poder registrar y filtrar por tipo.
"""

from dataclasses import dataclass

CLIENTE = "cliente"
IMPLEMENTADOR = "implementador"
ADMIN = "admin"
SISTEMA = "sistema"
SERVICIO = "servicio"
AGENTE = "agente"

TIPOS = (CLIENTE, IMPLEMENTADOR, ADMIN, SISTEMA, SERVICIO, AGENTE)
TIPOS_DEL_EQUIPO = (IMPLEMENTADOR, ADMIN)


@dataclass(frozen=True)
class Actor:
    tipo: str
    ref: str = ""

    def __post_init__(self):
        if self.tipo not in TIPOS:
            raise ValueError(f"Tipo de actor desconocido: {self.tipo!r}")

    @classmethod
    def de_usuario(cls, usuario):
        """El actor que corresponde a una cuenta: superusuario = admin, staff = implementador, el
        resto = cliente. Sin cuenta (o anónimo) actúa el sistema."""
        if usuario is None or not getattr(usuario, "is_authenticated", False):
            return SISTEMA_PORTAL
        if usuario.is_superuser:
            return cls(ADMIN, usuario.get_username())
        if usuario.is_staff:
            return cls(IMPLEMENTADOR, usuario.get_username())
        return cls(CLIENTE, usuario.get_username())

    @classmethod
    def cliente(cls, ref=""):
        return cls(CLIENTE, ref)

    @classmethod
    def implementador(cls, ref=""):
        return cls(IMPLEMENTADOR, ref)

    @property
    def es_del_equipo(self):
        return self.tipo in TIPOS_DEL_EQUIPO

    @property
    def etiqueta(self):
        """El texto que se guarda como "editado por" en el historial de versiones (como siempre:
        "Cliente" para el cliente, el nombre de usuario para el equipo)."""
        return "Cliente" if self.tipo == CLIENTE else (self.ref or self.tipo)


SISTEMA_PORTAL = Actor(SISTEMA, "portal")
