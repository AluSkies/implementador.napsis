from django.apps import AppConfig


class EmployeesConfig(AppConfig):
    name = 'employees'

    def ready(self):
        from clients.services import registrar_snapshot_builder

        from .services import snapshot_empleados

        registrar_snapshot_builder("empleados", snapshot_empleados)
