/* Tabla de integrantes de un grupo: buscador y contador de tildados.
   El formulario funciona igual sin esto (son casillas comunes); el script solo ayuda cuando hay muchos implementadores. */
(function () {
    "use strict";
    var caja = document.querySelector("[data-integrantes]");
    if (!caja) { return; }
    var buscador = caja.querySelector("[data-buscar]");
    var contador = caja.querySelector("[data-contador]");
    var sinCoincidencias = caja.querySelector("[data-sin-coincidencias]");
    var filas = Array.prototype.slice.call(caja.querySelectorAll("tr[data-fila]"));

    function contar() {
        var n = caja.querySelectorAll("input[name=integrantes]:checked").length;
        contador.textContent = n === 1 ? "1 tildado" : n + " tildados";
    }

    function recortar() {
        var q = buscador.value.trim().toLowerCase();
        var visibles = 0;
        filas.forEach(function (fila) {
            var coincide = !q || fila.textContent.toLowerCase().indexOf(q) >= 0 ||
                (fila.querySelector("label").title || "").toLowerCase().indexOf(q) >= 0;
            fila.hidden = !coincide;
            if (coincide) { visibles += 1; }
        });
        if (sinCoincidencias) { sinCoincidencias.hidden = visibles > 0 || filas.length === 0; }
    }

    buscador.addEventListener("input", recortar);
    /* Enter en el buscador no tiene que enviar el formulario. */
    buscador.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); } });
    caja.addEventListener("change", contar);
    contar();
})();
