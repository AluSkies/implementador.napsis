// Documentos del legajo: si el equipo fijó un máximo (data-maximo > 0), el contador va bajando a medida que el
// cliente elige y, al llegar a cero, bloquea el resto hasta que desmarque alguno. Los «otros documentos» de la
// caja de texto cuentan igual (una línea «Nombre: campo, campo» es un documento). Sin máximo (0) no limita nada.
// El servidor valida el tope de todos modos: esto es la comodidad de verlo mientras se elige.
(function () {
    "use strict";
    var formulario = document.querySelector("[data-documentos]");
    if (!formulario) { return; }
    var maximo = parseInt(formulario.dataset.maximo, 10) || 0;
    var casillas = [].slice.call(formulario.querySelectorAll('table.documentos input[type="checkbox"]'));
    var otros = formulario.querySelector('textarea[name="otros_documentos"]');
    var caja = formulario.querySelector("[data-cupo]");
    var texto = formulario.querySelector("[data-cupo-texto]");
    var detalle = formulario.querySelector("[data-cupo-detalle]");

    // Misma regla que DocumentosLegajoForm.parse_otros_documentos: «Nombre: campo1, campo2».
    function otrosElegidos() {
        if (!otros) { return 0; }
        return otros.value.split("\n").filter(function (linea) {
            var partes = linea.split(":");
            if (partes.length < 2 || !partes[0].trim()) { return false; }
            return partes.slice(1).join(":").split(",").some(function (campo) { return campo.trim() !== ""; });
        }).length;
    }

    function plural(n, uno, varios) { return n + " " + (n === 1 ? uno : varios); }

    function actualizar() {
        var elegidos = casillas.filter(function (c) { return c.checked; }).length + otrosElegidos();
        var restan = maximo - elegidos;
        if (maximo === 0) {
            texto.textContent = "Podés elegir todos los documentos que necesites";
            detalle.textContent = plural(elegidos, "elegido", "elegidos");
            caja.classList.remove("agotado", "excedido");
        } else {
            texto.textContent = restan > 0 ? "Podés elegir " + plural(restan, "documento más", "documentos más")
                : (restan === 0 ? "Llegaste al máximo de documentos" : "Elegiste " + plural(-restan, "documento", "documentos") + " de más");
            detalle.textContent = elegidos + " de " + maximo + " elegidos" + (restan < 0 ? " · quitá los que sobran para continuar" : (restan === 0 ? " · desmarcá uno para elegir otro" : ""));
            caja.classList.toggle("agotado", restan === 0);
            caja.classList.toggle("excedido", restan < 0);
        }
        casillas.forEach(function (c) {
            var bloquear = maximo > 0 && restan <= 0 && !c.checked;
            c.disabled = bloquear;
            c.closest("tr").classList.toggle("bloqueada", bloquear);
        });
    }

    casillas.forEach(function (c) { c.addEventListener("change", actualizar); });
    if (otros) { otros.addEventListener("input", actualizar); }
    actualizar();
})();
