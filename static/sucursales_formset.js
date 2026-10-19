/* Sucursales: una tarjeta visible y un botón para agregar todas las que haga falta.

   La página trae una tarjeta por cada sucursal ya cargada (o una vacía si no hay ninguna) y una
   plantilla escondida con el formulario vacío. «Agregar sucursal» copia esa plantilla con el número
   que sigue y avisa al formulario cuántas tarjetas hay (TOTAL_FORMS), que es lo que Django lee al
   guardar: no hay un tope de sucursales. «Quitar» no borra la tarjeta del documento sino que la
   esconde y tilda su casilla de eliminar, así los números de las demás no cambian. */
(function () {
    "use strict";

    function iniciar(raiz) {
        var total = raiz.querySelector('input[name$="-TOTAL_FORMS"]');
        var lista = raiz.querySelector("[data-lista]");
        var plantilla = raiz.querySelector("template[data-vacia]");
        var agregar = raiz.querySelector("[data-agregar]");
        if (!total || !lista || !plantilla || !agregar) { return; }

        function numerar() {
            var n = 0;
            lista.querySelectorAll("[data-tarjeta]").forEach(function (tarjeta) {
                if (tarjeta.hidden) { return; }
                n += 1;
                tarjeta.querySelector("[data-titulo]").textContent = "Sucursal " + n;
            });
        }

        function enlazar(tarjeta) {
            tarjeta.querySelector("[data-quitar]").addEventListener("click", function () {
                var eliminar = tarjeta.querySelector('input[name$="-DELETE"]');
                if (eliminar) { eliminar.checked = true; }
                tarjeta.hidden = true;
                numerar();
            });
        }

        lista.querySelectorAll("[data-tarjeta]").forEach(enlazar);
        numerar();

        agregar.addEventListener("click", function () {
            var indice = parseInt(total.value, 10);
            var contenedor = document.createElement("div");
            contenedor.innerHTML = plantilla.innerHTML.replace(/__prefix__/g, String(indice)).trim();
            var tarjeta = contenedor.firstElementChild;
            lista.appendChild(tarjeta);
            total.value = String(indice + 1);
            enlazar(tarjeta);
            numerar();
            var primero = tarjeta.querySelector("input[type=text]");
            if (primero) { primero.focus(); }
        });
    }

    document.querySelectorAll("[data-sucursales]").forEach(iniciar);
})();
