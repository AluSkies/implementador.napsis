/* Selector de fecha con días deshabilitados.

   El calendario que trae cada navegador no siempre muestra bien los días que no se pueden elegir. Este
   selector dibuja su propio calendario: los días anteriores a la fecha mínima (data-minima, AAAA-MM-DD)
   salen en gris y no se pueden tocar. La fecha se muestra y se envía como DD/MM/AAAA. Sin JavaScript el
   campo sigue siendo un <input type="date"> con su atributo min, y el servidor valida igual en los dos casos. */
(function () {
    "use strict";

    var MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
    var DIAS = ["Lu", "Ma", "Mi", "Ju", "Vi", "Sá", "Do"];

    function dosDigitos(n) { return (n < 10 ? "0" : "") + n; }
    function aIso(d) { return d.getFullYear() + "-" + dosDigitos(d.getMonth() + 1) + "-" + dosDigitos(d.getDate()); }
    function aTexto(d) { return dosDigitos(d.getDate()) + "/" + dosDigitos(d.getMonth() + 1) + "/" + d.getFullYear(); }
    function desdeIso(iso) {
        var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
        return m ? new Date(parseInt(m[1], 10), parseInt(m[2], 10) - 1, parseInt(m[3], 10)) : null;
    }
    function desdeTexto(texto) {
        var m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(texto || "");
        return m ? new Date(parseInt(m[3], 10), parseInt(m[2], 10) - 1, parseInt(m[1], 10)) : null;
    }
    function mismoDia(a, b) { return a && b && aIso(a) === aIso(b); }

    function iniciar(campo) {
        var minima = desdeIso(campo.getAttribute("data-minima"));
        var elegida = desdeIso(campo.value) || desdeTexto(campo.value);
        var hoy = new Date();
        hoy = new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate());
        // Arranca en el mes de la fecha elegida o, si no hay, en el actual: así se ven en gris los días que no se pueden elegir.
        var mostrado = elegida || hoy;
        mostrado = new Date(mostrado.getFullYear(), mostrado.getMonth(), 1);

        // El campo pasa a ser de solo lectura: se elige con el calendario (así no se escribe una fecha que no corresponde).
        campo.type = "text";
        campo.readOnly = true;
        campo.placeholder = "dd/mm/aaaa";
        campo.value = elegida ? aTexto(elegida) : "";
        campo.setAttribute("autocomplete", "off");
        campo.classList.add("selector-de-fecha-campo");

        var envoltorio = document.createElement("div");
        envoltorio.className = "selector-de-fecha";
        campo.parentNode.insertBefore(envoltorio, campo);
        envoltorio.appendChild(campo);
        var panel = document.createElement("div");
        panel.className = "selector-de-fecha-panel";
        panel.hidden = true;
        panel.setAttribute("role", "dialog");
        panel.setAttribute("aria-label", "Elegir una fecha");
        envoltorio.appendChild(panel);

        function abrir() { panel.hidden = false; dibujar(); }
        function cerrar() { panel.hidden = true; }

        function elegir(dia) {
            elegida = dia;
            campo.value = aTexto(dia);
            campo.dispatchEvent(new Event("change", { bubbles: true }));
            cerrar();
        }

        function dibujar() {
            panel.innerHTML = "";
            var cabecera = document.createElement("div");
            cabecera.className = "selector-de-fecha-cabecera";
            var anterior = document.createElement("button");
            anterior.type = "button";
            anterior.textContent = "‹";
            anterior.setAttribute("aria-label", "Mes anterior");
            // no se navega a meses anteriores al actual: ya pasaron
            anterior.disabled = new Date(mostrado.getFullYear(), mostrado.getMonth(), 0) < hoy;
            anterior.addEventListener("click", function () { mostrado = new Date(mostrado.getFullYear(), mostrado.getMonth() - 1, 1); dibujar(); });
            var siguiente = document.createElement("button");
            siguiente.type = "button";
            siguiente.textContent = "›";
            siguiente.setAttribute("aria-label", "Mes siguiente");
            siguiente.addEventListener("click", function () { mostrado = new Date(mostrado.getFullYear(), mostrado.getMonth() + 1, 1); dibujar(); });
            var titulo = document.createElement("strong");
            titulo.textContent = MESES[mostrado.getMonth()] + " " + mostrado.getFullYear();
            cabecera.appendChild(anterior);
            cabecera.appendChild(titulo);
            cabecera.appendChild(siguiente);
            panel.appendChild(cabecera);

            var grilla = document.createElement("div");
            grilla.className = "selector-de-fecha-grilla";
            DIAS.forEach(function (nombre) {
                var celda = document.createElement("span");
                celda.className = "selector-de-fecha-dia-nombre";
                celda.textContent = nombre;
                grilla.appendChild(celda);
            });
            var primero = new Date(mostrado.getFullYear(), mostrado.getMonth(), 1);
            var huecos = (primero.getDay() + 6) % 7; // la semana arranca el lunes
            for (var h = 0; h < huecos; h++) { grilla.appendChild(document.createElement("span")); }
            var ultimo = new Date(mostrado.getFullYear(), mostrado.getMonth() + 1, 0).getDate();
            for (var n = 1; n <= ultimo; n++) {
                var dia = new Date(mostrado.getFullYear(), mostrado.getMonth(), n);
                var boton = document.createElement("button");
                boton.type = "button";
                boton.textContent = String(n);
                boton.className = "selector-de-fecha-dia";
                var finDeSemana = dia.getDay() === 0 || dia.getDay() === 6;
                if (finDeSemana) { boton.classList.add("fin-de-semana"); }
                if (dia < hoy || (minima && dia < minima)) {
                    boton.disabled = true;
                    boton.title = "No disponible: hace falta un mínimo de días hábiles";
                } else {
                    (function (d) { boton.addEventListener("click", function () { elegir(d); }); })(dia);
                }
                if (mismoDia(dia, elegida)) { boton.classList.add("elegido"); }
                grilla.appendChild(boton);
            }
            panel.appendChild(grilla);

            var pie = document.createElement("div");
            pie.className = "selector-de-fecha-pie";
            if (minima) {
                var leyenda = document.createElement("span");
                leyenda.textContent = "Los días en gris no están disponibles: la primera fecha posible es el " + aTexto(minima) + ".";
                pie.appendChild(leyenda);
            }
            var quitar = document.createElement("button");
            quitar.type = "button";
            quitar.textContent = "Quitar fecha";
            quitar.addEventListener("click", function () { elegida = null; campo.value = ""; campo.dispatchEvent(new Event("change", { bubbles: true })); cerrar(); });
            pie.appendChild(quitar);
            panel.appendChild(pie);
        }

        campo.addEventListener("click", abrir);
        campo.addEventListener("focus", abrir);
        campo.addEventListener("keydown", function (e) {
            if (e.key === "Escape") { cerrar(); }
            if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrir(); }
        });
        document.addEventListener("click", function (e) { if (!envoltorio.contains(e.target)) { cerrar(); } });
    }

    document.querySelectorAll("input[data-selector-de-fecha]").forEach(iniciar);
})();
