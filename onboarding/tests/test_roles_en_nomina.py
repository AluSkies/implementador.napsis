"""El Apoderado/Firmante y el Liquidador los elige Napsis de la nómina: tienen que ser empleados cargados."""

from automatizacion.actores import Actor
from clients.models import PersonaRol
from employees.models import Empleado
from onboarding import services
from onboarding.tests.test_wizard import BaseWizard, _url

CLIENTE = Actor.cliente("cliente_a")


class RolesDelWizardTests(BaseWizard):
    def post_roles(self, *filas):
        """filas: (rol, nombre, cuil)"""
        datos = {"form-TOTAL_FORMS": str(len(filas)), "form-INITIAL_FORMS": "0"}
        for i, (rol, nombre, cuil) in enumerate(filas):
            datos.update({f"form-{i}-rol": rol, f"form-{i}-apellido_nombre": nombre, f"form-{i}-cuil": cuil, f"form-{i}-mail": ""})
        return self.client.post(_url(self.implementacion, 5), datos)

    def completas(self, apoderado=BaseWizard.CUIL_APODERADO, liquidador=BaseWizard.CUIL_LIQUIDADOR, admin=""):
        return [
            (PersonaRol.ROL_APODERADO, "Gomez, Ana", apoderado), (PersonaRol.ROL_LIQUIDADOR, "Ruiz, Luis", liquidador),
            (PersonaRol.ROL_ADMIN_RRHH, "Sosa, Eva", admin),
        ]

    def test_con_la_nomina_cargada_guarda_y_vincula_a_cada_persona_con_su_empleado(self):
        self.agregar_empleado(self.CUIL_APODERADO)
        self.agregar_empleado(self.CUIL_LIQUIDADOR, "LUIS", "RUIZ")
        self.assertEqual(self.post_roles(*self.completas()).status_code, 302)
        apoderado = self.implementacion.roles.get(rol=PersonaRol.ROL_APODERADO)
        self.assertEqual(apoderado.empleado.cuil, self.CUIL_APODERADO)
        self.assertIsNone(self.implementacion.roles.get(rol=PersonaRol.ROL_ADMIN_RRHH).empleado)

    def test_el_cuil_con_guiones_se_normaliza_y_coincide(self):
        self.agregar_empleado(self.CUIL_APODERADO)
        self.agregar_empleado(self.CUIL_LIQUIDADOR, "LUIS", "RUIZ")
        self.post_roles(*self.completas(apoderado="20-11111111-2"))
        self.assertEqual(self.implementacion.roles.get(rol=PersonaRol.ROL_APODERADO).cuil, self.CUIL_APODERADO)
        self.assertIsNotNone(self.implementacion.roles.get(rol=PersonaRol.ROL_APODERADO).empleado)

    def test_un_apoderado_que_no_esta_en_la_nomina_se_rechaza_con_el_motivo(self):
        self.agregar_empleado(self.CUIL_APODERADO)
        self.agregar_empleado(self.CUIL_LIQUIDADOR, "LUIS", "RUIZ")
        respuesta = self.post_roles(*self.completas(apoderado="20999999990"))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "Este CUIL no está en la nómina")
        self.assertFalse(self.implementacion.roles.exists())

    def test_sin_cuil_se_rechaza_para_los_roles_que_salen_de_la_nomina(self):
        self.agregar_empleado(self.CUIL_APODERADO)
        self.agregar_empleado(self.CUIL_LIQUIDADOR, "LUIS", "RUIZ")
        respuesta = self.post_roles(*self.completas(liquidador=""))
        self.assertContains(respuesta, "elegí a la persona de la lista o escribí su CUIL")

    def test_con_la_nomina_vacia_dice_que_hay_que_cargarla_primero(self):
        respuesta = self.post_roles(*self.completas())
        self.assertContains(respuesta, "Todavía no cargaste la nómina")

    def test_el_admin_de_rrhh_no_necesita_estar_en_la_nomina(self):
        self.agregar_empleado(self.CUIL_APODERADO)
        self.agregar_empleado(self.CUIL_LIQUIDADOR, "LUIS", "RUIZ")
        self.assertEqual(self.post_roles(*self.completas(admin="20999999990")).status_code, 302)

    def test_un_cuil_que_no_tiene_11_digitos_se_rechaza(self):
        self.agregar_empleado(self.CUIL_APODERADO)
        self.agregar_empleado(self.CUIL_LIQUIDADOR, "LUIS", "RUIZ")
        respuesta = self.post_roles(*self.completas(admin="123"))
        self.assertContains(respuesta, "11 dígitos")


class VinculoConLaNominaTests(BaseWizard):
    def setUp(self):
        super().setUp()
        self.cargar_roles_completos()

    def apoderado(self):
        return self.implementacion.roles.get(rol=PersonaRol.ROL_APODERADO)

    def test_si_se_borra_el_empleado_el_vinculo_queda_vacio_y_el_control_lo_avisa(self):
        empleado = self.apoderado().empleado or Empleado.objects.get(cuil=self.CUIL_APODERADO)
        services.vincular_roles_con_nomina(self.implementacion)
        self.assertEqual(self.apoderado().empleado, empleado)
        services.eliminar_empleado(self.implementacion, str(empleado.pk), CLIENTE)
        self.assertIsNone(self.apoderado().empleado)
        mensajes = [p["mensaje"] for p in services.pendientes_de_envio(self.implementacion)]
        self.assertTrue(any("Gomez, Ana (Apoderado / Firmante) no figura en la nómina" in m for m in mensajes))

    def test_si_el_empleado_se_carga_despues_el_rol_se_vincula(self):
        Empleado.objects.filter(cuil=self.CUIL_APODERADO).delete()
        self.assertIsNone(self.apoderado().empleado)
        self.agregar_empleado(self.CUIL_APODERADO)
        services.vincular_roles_con_nomina(self.implementacion)
        self.assertEqual(self.apoderado().empleado.cuil, self.CUIL_APODERADO)

    def test_agregar_a_mano_un_empleado_vincula_el_rol_que_lo_esperaba(self):
        from employees.forms import EmpleadoForm

        Empleado.objects.filter(cuil=self.CUIL_APODERADO).delete()
        formulario = EmpleadoForm(
            {"cuil": self.CUIL_APODERADO, "nombre": "Ana", "apellido": "Gomez", "fecha_ingreso": "2020-01-01"},
            implementacion=self.implementacion,
        )
        self.assertTrue(services.agregar_empleado(self.implementacion, formulario, CLIENTE))
        self.assertEqual(self.apoderado().empleado.cuil, self.CUIL_APODERADO)

    def test_con_todo_en_la_nomina_el_control_no_marca_los_roles(self):
        mensajes = [p["mensaje"] for p in services.pendientes_de_envio(self.implementacion)]
        self.assertFalse([m for m in mensajes if "no figura en la nómina" in m])

    def test_el_admin_de_rrhh_sin_nomina_no_se_marca(self):
        self.assertFalse([
            p for p in services.pendientes_de_envio(self.implementacion) if "Sosa, Eva" in p["mensaje"]
        ])

    def test_un_rol_sin_cuil_se_marca(self):
        self.implementacion.roles.filter(rol=PersonaRol.ROL_LIQUIDADOR).update(cuil="", empleado=None)
        mensajes = [p["mensaje"] for p in services.pendientes_de_envio(self.implementacion)]
        self.assertTrue(any("Ruiz, Luis" in m for m in mensajes))
