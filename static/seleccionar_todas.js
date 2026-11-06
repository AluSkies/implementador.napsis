// «Seleccionar todas» para los checklists: cualquier contenedor con data-seleccionable recibe, arriba, un botón que
// tilda todas sus casillas y, si ya están todas tildadas, las destilda. El valor del atributo es el género de la
// etiqueta («todas» o «todos»). No toca lo que no se puede cambiar: las casillas deshabilitadas (por ejemplo, las que
// dejó fijas el equipo) y las marcadas con data-fijo (el módulo obligatorio). Sin casillas editables no hay botón.
// Cada casilla cambiada dispara su evento «change», así los contadores y reglas de la página (como el cupo de
// documentos) se enteran.
(function () {
    "use strict";

    function casillas(contenedor) {
        return [].slice.call(contenedor.querySelectorAll('input[type="checkbox"]:not(:disabled):not([data-fijo])'));
    }

    function montar(contenedor) {
        var lista = casillas(contenedor);
        if (!lista.length) { return; }
        var genero = contenedor.dataset.seleccionable === "todos" ? "todos" : "todas";
        var fila = document.createElement("div");
        fila.className = "seleccion-masiva";
        var boton = document.createElement("button");
        boton.type = "button";
        fila.appendChild(boton);
        contenedor.parentNode.insertBefore(fila, contenedor);

        function etiquetar() {
            boton.textContent = lista.every(function (c) { return c.checked; }) ? "Quitar " + genero : "Seleccionar " + genero;
        }
        boton.addEventListener("click", function () {
            var marcar = !lista.every(function (c) { return c.checked; });
            lista.forEach(function (c) {
                if (c.checked !== marcar) {
                    c.checked = marcar;
                    c.dispatchEvent(new Event("change", { bubbles: true }));
                }
            });
            etiquetar();
        });
        lista.forEach(function (c) { c.addEventListener("change", etiquetar); });
        etiquetar();
    }

    document.querySelectorAll("[data-seleccionable]").forEach(montar);
})();
