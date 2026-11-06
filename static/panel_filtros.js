/* Filtros del listado de implementaciones.

   Los filtros viajan por la URL (el formulario es un GET): este script solo hace más cómodo usarlos.
   - Al tildar una casilla o cambiar una fecha, se aplica solo (sin tocar «Aplicar filtros»).
   - Tildar el título de un grupo marca o desmarca a todos sus integrantes.
   - Lo que se escribe en «Buscar empresa» recorta la lista de empresas al instante; con Enter se aplica como filtro.
   - Como aplicar recarga la página, se recuerda hasta dónde estaba desplazada cada lista.
   - Los campos vacíos no viajan: la URL queda solo con lo que se filtra. */
(function () {
    "use strict";
    var formulario = document.getElementById("form-filtros");
    if (!formulario) { return; }
    var CLAVE = "panel-filtros-scroll";

    /* --- recordar el desplazamiento de las listas entre una carga y la siguiente */
    var listas = Array.prototype.slice.call(formulario.querySelectorAll(".lista"));
    try {
        var guardado = JSON.parse(sessionStorage.getItem(CLAVE) || "[]");
        listas.forEach(function (lista, i) { if (guardado[i]) { lista.scrollTop = guardado[i]; } });
    } catch (e) { /* sin sessionStorage: se arranca desde arriba */ }
    function recordar() {
        try { sessionStorage.setItem(CLAVE, JSON.stringify(listas.map(function (l) { return l.scrollTop; }))); } catch (e) { /* nada */ }
    }

    function aplicar() {
        recordar();
        if (typeof formulario.requestSubmit === "function") { formulario.requestSubmit(); } else { formulario.submit(); }
    }

    /* --- grupos: el título marca a todos los integrantes */
    function integrantesDe(titulo) {
        var gente = [];
        for (var el = titulo.nextElementSibling; el && !el.classList.contains("grupo-t") && !el.classList.contains("separada"); el = el.nextElementSibling) {
            var caja = el.querySelector("input[data-del-grupo]");
            if (caja) { gente.push(caja); }
        }
        return gente;
    }
    function sincronizarTitulo(titulo) {
        var gente = integrantesDe(titulo);
        var marcadas = gente.filter(function (c) { return c.checked; }).length;
        var caja = titulo.querySelector("input[data-grupo]");
        caja.checked = gente.length > 0 && marcadas === gente.length;
        caja.indeterminate = marcadas > 0 && marcadas < gente.length;
    }
    Array.prototype.forEach.call(formulario.querySelectorAll(".grupo-t"), sincronizarTitulo);

    formulario.addEventListener("change", function (evento) {
        var caja = evento.target;
        if (caja.matches("input[data-grupo]")) {
            integrantesDe(caja.closest(".grupo-t")).forEach(function (c) { c.checked = caja.checked; });
            aplicar();
        } else if (caja.matches("input[type=checkbox]") || caja.matches("input[type=date]")) {
            aplicar();
        }
    });

    /* --- empresas: recortar la lista mientras se escribe */
    var buscador = formulario.querySelector("[data-buscar-empresa]");
    var listaDeEmpresas = formulario.querySelector("[data-lista-empresas]");
    if (buscador && listaDeEmpresas) {
        var sinCoincidencias = listaDeEmpresas.querySelector("[data-sin-coincidencias]");
        var recortar = function () {
            var q = buscador.value.trim().toLowerCase();
            var visibles = 0;
            Array.prototype.forEach.call(listaDeEmpresas.querySelectorAll(".opcion"), function (opcion) {
                var coincide = !q || opcion.textContent.toLowerCase().indexOf(q) >= 0;
                opcion.hidden = !coincide;
                if (coincide) { visibles += 1; }
            });
            if (sinCoincidencias) { sinCoincidencias.hidden = visibles > 0; }
        };
        buscador.addEventListener("input", recortar);
        recortar();
    }

    formulario.addEventListener("submit", recordar);

    /* No mandar los campos vacíos: la URL queda con lo que realmente se filtra (y se puede compartir). */
    formulario.addEventListener("formdata", function (evento) {
        Array.from(evento.formData.entries()).forEach(function (par) {
            if (par[1] === "") { evento.formData.delete(par[0]); }
        });
    });
})();
