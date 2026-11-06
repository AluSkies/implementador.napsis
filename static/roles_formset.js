// Roles del wizard: cada persona es una tarjeta con su botón «Quitar». El formset de Django sigue
// funcionando con su casilla DELETE (que acá queda oculta): el botón la tilda y la tarjeta se
// pliega a una línea con «Deshacer». Al continuar, el servidor descarta las filas quitadas.
(function () {
    "use strict";

    function actualizar(tarjeta, quitada) {
        var casilla = tarjeta.querySelector("[data-quitar-casilla] input");
        if (casilla) { casilla.checked = quitada; }
        tarjeta.classList.toggle("persona-quitada", quitada);
        tarjeta.querySelector("[data-persona-cuerpo]").hidden = quitada;
        tarjeta.querySelector("[data-persona-aviso]").hidden = !quitada;
        tarjeta.querySelector("[data-persona-quitar]").hidden = quitada;
    }

    document.querySelectorAll("[data-persona]").forEach(function (tarjeta) {
        var quitar = tarjeta.querySelector("[data-persona-quitar]");
        var deshacer = tarjeta.querySelector("[data-persona-deshacer]");
        quitar.addEventListener("click", function () { actualizar(tarjeta, true); });
        deshacer.addEventListener("click", function () { actualizar(tarjeta, false); });
        var casilla = tarjeta.querySelector("[data-quitar-casilla] input");
        if (casilla && casilla.checked) { actualizar(tarjeta, true); }  // el servidor la devolvió quitada
    });
})();
