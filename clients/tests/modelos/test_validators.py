from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from clients.validators import normalizar_cuits


class NormalizarCuitsTests(SimpleTestCase):
    """Un CUIT mal tipeado en el alta es retrabajo asegurado: se valida el dígito verificador."""

    def test_acepta_con_o_sin_guiones_y_los_formatea(self):
        self.assertEqual(normalizar_cuits("30500010912"), "30-50001091-2")
        self.assertEqual(normalizar_cuits("30-50001091-2"), "30-50001091-2")
        self.assertEqual(normalizar_cuits(" 30 50001091 2 "), "30-50001091-2")

    def test_varios_separados_por_coma(self):
        self.assertEqual(normalizar_cuits("30-50001091-2, 20111111112"), "30-50001091-2, 20-11111111-2")

    def test_ignora_entradas_vacias(self):
        self.assertEqual(normalizar_cuits("30-50001091-2,, "), "30-50001091-2")

    def test_rechaza_un_verificador_incorrecto(self):
        with self.assertRaises(ValidationError):
            normalizar_cuits("30-50001091-3")

    def test_rechaza_largo_incorrecto_y_letras(self):
        for invalido in ("123", "30-5000109-2", "abcdefghijk", "30-50001091-22"):
            with self.subTest(invalido=invalido), self.assertRaises(ValidationError):
                normalizar_cuits(invalido)

    def test_el_mensaje_dice_cual_cuit_esta_mal(self):
        with self.assertRaisesMessage(ValidationError, "30-50001091-3"):
            normalizar_cuits("30-50001091-2, 30-50001091-3")

    def test_prefijo_23_con_verificador_asignado(self):
        """Cuando el verificador da 10, AFIP emite el CUIT con prefijo 23 y 9 (varón) o 4 (mujer)."""
        self.assertEqual(normalizar_cuits("23200000099"), "23-20000009-9")
        self.assertEqual(normalizar_cuits("23200000064"), "23-20000006-4")

    def test_prefijo_23_con_el_verificador_equivocado_se_rechaza(self):
        with self.assertRaises(ValidationError):
            normalizar_cuits("23200000094")


class MensajesDelCuitTests(SimpleTestCase):
    """El mensaje dice cuál es el problema: la cantidad de dígitos o el dígito verificador."""

    def mensaje(self, cuit):
        with self.assertRaises(ValidationError) as contexto:
            normalizar_cuits(cuit)
        return contexto.exception.messages[0]

    def test_de_mas_o_de_menos_dice_cuantos_tiene(self):
        self.assertIn("tiene 12 dígitos y tiene que tener 11", self.mensaje("305213151205"))
        self.assertIn("tiene 10 dígitos y tiene que tener 11", self.mensaje("30-5213151-2"))

    def test_con_11_dígitos_y_verificador_malo_habla_del_verificador(self):
        mensaje = self.mensaje("30521315126")
        self.assertIn("tiene 11 dígitos pero el último no corresponde", mensaje)
        self.assertIn("30521315126", mensaje)

    def test_el_verificador_correcto_de_esos_diez_digitos_es_valido(self):
        self.assertEqual(normalizar_cuits("30521315128"), "30-52131512-8")
