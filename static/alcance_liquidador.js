/* Editor del alcance del Liquidador: de qué empleados ve los recibos.

   Se dibuja dentro de cada fila de rol cuando el rol elegido es «Liquidador». Tiene dos listas, y el alcance
   es la unión de las dos: grupos de la nómina («todos los del puesto OPERARIO») y personas sueltas (por
   ejemplo, los gerentes). Sin nada cargado, ve todos los recibos. Todo lo que muestra sale de la nómina
   que se pasa en el JSON #alcance-datos; lo que se arma queda en el campo oculto «…-alcance» (JSON).
   El servidor valida igual: este script es solo la comodidad de armarlo con listas. */
(function () {
    "use strict";
    var origen = document.getElementById("alcance-datos");
    if (!origen) { return; }
    var datos = JSON.parse(origen.textContent);
    if (!datos.editable) { return; }

    function el(etiqueta, clase, texto) {
        var nodo = document.createElement(etiqueta);
        if (clase) { nodo.className = clase; }
        if (texto !== undefined) { nodo.textContent = texto; }
        return nodo;
    }
    function boton(texto, alClick, clase) {
        var b = el("button", clase || "btn secondary", texto);
        b.type = "button";
        b.addEventListener("click", alClick);
        return b;
    }

    function montar(grupo) {
        var campoRol = grupo.querySelector('[name$="-rol"]');
        var campoAlcance = grupo.querySelector('[name$="-alcance"]');
        if (!campoRol || !campoAlcance) { return; }
        var estado;
        try { estado = JSON.parse(campoAlcance.value || "{}"); } catch (e) { estado = {}; }
        estado.reglas = estado.reglas || [];
        estado.cuils = estado.cuils || [];

        var caja = el("div", "alcance-liquidador");
        var titulo = el("strong", null, "¿Qué recibos ve el liquidador?");
        var ayuda = el("p", "muted", "Si no lo limitás, ve los de todos. Si querés limitarlo, armá una lista de grupos " +
            "de la nómina (por ejemplo, todos los de un puesto o un sector) y, aparte, sumá personas una por una.");
        var vetodo = el("label", "checkbox-row");
        var tilde = document.createElement("input");
        tilde.type = "checkbox";
        vetodo.appendChild(tilde);
        vetodo.appendChild(document.createTextNode(" Ve los recibos de todos (sin segmentar)"));
        var armado = el("div", "alcance-armado");
        var resumen = el("p", "alcance-resumen");
        caja.appendChild(titulo); caja.appendChild(ayuda); caja.appendChild(vetodo); caja.appendChild(armado); caja.appendChild(resumen);

        /* grupos de la nómina */
        var filaRegla = el("div", "alcance-fila");
        var selCampo = document.createElement("select");
        Object.keys(datos.campos).forEach(function (clave) {
            var o = el("option", null, datos.campos[clave]); o.value = clave; selCampo.appendChild(o);
        });
        var selValor = document.createElement("select");
        function cargarValores() {
            selValor.innerHTML = "";
            (datos.opciones[selCampo.value] || []).forEach(function (v) {
                var o = el("option", null, v); o.value = v; selValor.appendChild(o);
            });
        }
        selCampo.addEventListener("change", cargarValores);
        cargarValores();
        filaRegla.appendChild(selCampo); filaRegla.appendChild(selValor);
        filaRegla.appendChild(boton("Agregar grupo", function () {
            if (!selValor.value) { return; }
            var repetida = estado.reglas.some(function (r) { return r.campo === selCampo.value && r.valor === selValor.value; });
            if (!repetida) { estado.reglas.push({ campo: selCampo.value, valor: selValor.value }); }
            guardar();
        }));
        var chipsReglas = el("div", "alcance-chips");
        armado.appendChild(el("label", null, "Grupos de la nómina")); armado.appendChild(filaRegla); armado.appendChild(chipsReglas);

        /* personas sueltas */
        var lista = document.createElement("datalist");
        lista.id = "alcance-personas-" + Math.random().toString(36).slice(2);
        datos.empleados.forEach(function (e) {
            var o = document.createElement("option"); o.value = e.nombre + " — " + e.cuil; lista.appendChild(o);
        });
        var buscador = document.createElement("input");
        buscador.type = "text"; buscador.setAttribute("list", lista.id); buscador.autocomplete = "off";
        buscador.placeholder = "Buscar por apellido, nombre o CUIL";
        var filaPersona = el("div", "alcance-fila");
        filaPersona.appendChild(buscador);
        filaPersona.appendChild(boton("Agregar persona", function () {
            var coincide = datos.empleados.filter(function (e) { return (e.nombre + " — " + e.cuil) === buscador.value; })[0];
            if (!coincide) { buscador.setCustomValidity("Elegí a una persona de la lista."); buscador.reportValidity(); buscador.setCustomValidity(""); return; }
            if (estado.cuils.indexOf(coincide.cuil) < 0) { estado.cuils.push(coincide.cuil); }
            buscador.value = "";
            guardar();
        }));
        var chipsPersonas = el("div", "alcance-chips");
        armado.appendChild(el("label", null, "Personas elegidas una por una")); armado.appendChild(filaPersona);
        armado.appendChild(lista); armado.appendChild(chipsPersonas);

        function chip(texto, alQuitar) {
            var c = el("span", "alcance-chip", texto + " ");
            var x = el("button", "alcance-quitar", "×");
            x.type = "button"; x.setAttribute("aria-label", "Quitar " + texto);
            x.addEventListener("click", alQuitar);
            c.appendChild(x);
            return c;
        }

        function cuantos() {
            if (!estado.reglas.length && !estado.cuils.length) { return datos.empleados.length; }
            return datos.empleados.filter(function (e) {
                return estado.cuils.indexOf(e.cuil) >= 0 || estado.reglas.some(function (r) {
                    return String(e[r.campo]).toLowerCase() === String(r.valor).toLowerCase();
                });
            }).length;
        }

        function nombreDe(cuil) {
            var e = datos.empleados.filter(function (x) { return x.cuil === cuil; })[0];
            return e ? e.nombre : cuil;
        }

        function dibujar() {
            var todos = !estado.reglas.length && !estado.cuils.length;
            tilde.checked = todos;
            armado.hidden = todos && tilde.dataset.cerrado !== "0";
            chipsReglas.innerHTML = ""; chipsPersonas.innerHTML = "";
            estado.reglas.forEach(function (r, i) {
                chipsReglas.appendChild(chip(datos.campos[r.campo] + ": " + r.valor, function () { estado.reglas.splice(i, 1); guardar(); }));
            });
            estado.cuils.forEach(function (c, i) {
                chipsPersonas.appendChild(chip(nombreDe(c), function () { estado.cuils.splice(i, 1); guardar(); }));
            });
            resumen.textContent = datos.empleados.length
                ? (todos ? "Ve los recibos de los " + datos.empleados.length + " empleados de la nómina."
                         : "Llega a " + cuantos() + " de los " + datos.empleados.length + " empleados de la nómina.")
                : "Todavía no hay nómina cargada: cuando la cargues vas a poder armar los grupos y elegir personas.";
        }

        function guardar() {
            campoAlcance.value = (estado.reglas.length || estado.cuils.length) ? JSON.stringify(estado) : "";
            tilde.dataset.cerrado = "";
            dibujar();
        }

        tilde.addEventListener("change", function () {
            if (tilde.checked) {
                estado.reglas = []; estado.cuils = [];
                tilde.dataset.cerrado = "";
                guardar();
            } else {
                tilde.dataset.cerrado = "0"; // destildado sin nada cargado todavía: se abre el armado
                dibujar();
            }
        });

        function segunRol() { caja.hidden = campoRol.value !== "liquidador"; }
        campoRol.addEventListener("change", segunRol);
        segunRol();
        grupo.appendChild(caja);
        dibujar();
    }

    document.querySelectorAll("fieldset").forEach(montar);
})();
