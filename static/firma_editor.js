/* Editor de la firma del recibo.

   El cliente ubica su firma sobre su modelo de recibo: arrastra y redimensiona tres recuadros (la firma de la
   empresa y las del empleado en conformidad y en disconformidad). Lo que se guarda es solo esa intención: la
   página y, para cada recuadro, posición y tamaño en % de la página. Los mismos valores están en campos
   numéricos (que son los que viajan en el formulario), así que sin JavaScript, sin poder arrastrar o si el
   recibo no se llega a mostrar, la firma se puede ubicar igual escribiendo los números.

   Para mostrar el PDF se usa PDF.js, copiado en static/vendor/pdfjs/ (no se baja de ningún CDN). */
(function () {
    "use strict";
    if (window.NapsisFirma) { return; }

    var PDFJS = document.currentScript.dataset.pdfjs;  // carpeta con pdf.min.js y pdf.worker.min.js
    var ELEMENTOS = [
        { codigo: "empresa", etiqueta: "Firma de la empresa" },
        { codigo: "conforme", etiqueta: "Empleado en conformidad" },
        { codigo: "disconforme", etiqueta: "Empleado en disconformidad" }
    ];
    var ANCHO_MIN = 3, ALTO_MIN = 2; // % de la página

    function acotar(valor, minimo, maximo) { return Math.min(Math.max(valor, minimo), maximo); }
    function redondear(valor) { return Math.round(valor * 10) / 10; }

    var pdfjsPendiente = null;
    function cargarPdfJs() {
        if (window.pdfjsLib) { return Promise.resolve(window.pdfjsLib); }
        if (!pdfjsPendiente) {
            pdfjsPendiente = new Promise(function (resolver, rechazar) {
                var script = document.createElement("script");
                script.src = PDFJS + "pdf.min.js";
                script.onload = function () {
                    window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS + "pdf.worker.min.js";
                    resolver(window.pdfjsLib);
                };
                script.onerror = function () { rechazar(new Error("No se pudo cargar PDF.js")); };
                document.head.appendChild(script);
            });
        }
        return pdfjsPendiente;
    }

    function Editor(raiz) {
        this.raiz = raiz;
        this.soloLectura = raiz.hasAttribute("data-solo-lectura");
        this.escenario = raiz.querySelector(".firma-escenario");
        this.aviso = raiz.querySelector(".firma-aviso");
        this.pagina = raiz.querySelector('[name="pagina"]');
        this.campos = {};
        this.cajas = {};
        this.pdf = null;
        var self = this;

        ELEMENTOS.forEach(function (elemento) {
            ["x", "y", "ancho", "alto"].forEach(function (campo) {
                var input = raiz.querySelector('[name="' + elemento.codigo + "_" + campo + '"]');
                if (input) { self.campos[elemento.codigo + "." + campo] = input; }
            });
        });

        this.canvas = document.createElement("canvas");
        this.canvas.className = "firma-canvas";
        this.escenario.appendChild(this.canvas);
        ELEMENTOS.forEach(function (elemento) { self.crearCaja(elemento); });

        Object.keys(this.campos).forEach(function (clave) {
            self.campos[clave].addEventListener("input", function () { self.dibujarCajas(); });
        });
        if (this.pagina && !this.soloLectura) {
            this.pagina.addEventListener("change", function () { self.dibujarPagina(); });
        }
        var archivo = raiz.querySelector('input[type="file"]');
        if (archivo) {
            archivo.addEventListener("change", function () {
                if (archivo.files && archivo.files[0]) { self.mostrarImagen(URL.createObjectURL(archivo.files[0])); }
            });
        }
        if (raiz.dataset.imagen) { this.mostrarImagen(raiz.dataset.imagen); }

        this.dibujarCajas();
        this.cargarRecibo();
        window.addEventListener("resize", function () { self.dibujarPagina(); });
    }

    Editor.prototype.valor = function (codigo, campo) {
        var input = this.campos[codigo + "." + campo];
        var numero = input ? parseFloat(String(input.value).replace(",", ".")) : NaN;
        return isNaN(numero) ? 0 : numero;
    };

    Editor.prototype.poner = function (codigo, campo, valor) {
        var input = this.campos[codigo + "." + campo];
        if (input) { input.value = redondear(valor); }
    };

    Editor.prototype.crearCaja = function (elemento) {
        var self = this;
        var caja = document.createElement("div");
        caja.className = "firma-caja firma-caja-" + elemento.codigo;
        caja.setAttribute("role", "img");
        caja.setAttribute("aria-label", elemento.etiqueta);
        var etiqueta = document.createElement("span");
        etiqueta.className = "firma-etiqueta";
        etiqueta.textContent = elemento.etiqueta;
        caja.appendChild(etiqueta);
        if (elemento.codigo === "empresa") {
            var imagen = document.createElement("img");
            imagen.className = "firma-imagen";
            imagen.alt = "";
            caja.appendChild(imagen);
            this.imagen = imagen;
        }
        if (!this.soloLectura) {
            caja.tabIndex = 0;
            caja.setAttribute("role", "slider");
            var asa = document.createElement("i");
            asa.className = "firma-asa";
            asa.title = "Arrastrá para cambiar el tamaño";
            caja.appendChild(asa);
            caja.addEventListener("pointerdown", function (e) { self.arrastrar(e, elemento.codigo, caja); });
            caja.addEventListener("keydown", function (e) { self.teclado(e, elemento.codigo); });
        }
        this.escenario.appendChild(caja);
        this.cajas[elemento.codigo] = caja;
    };

    Editor.prototype.dibujarCajas = function () {
        var self = this;
        ELEMENTOS.forEach(function (elemento) {
            var caja = self.cajas[elemento.codigo], c = elemento.codigo;
            caja.style.left = self.valor(c, "x") + "%";
            caja.style.top = self.valor(c, "y") + "%";
            caja.style.width = self.valor(c, "ancho") + "%";
            caja.style.height = self.valor(c, "alto") + "%";
        });
    };

    Editor.prototype.mostrarImagen = function (url) {
        if (this.imagen) { this.imagen.src = url; this.cajas.empresa.classList.add("con-imagen"); }
    };

    Editor.prototype.arrastrar = function (e, codigo, caja) {
        var self = this;
        if (e.button !== undefined && e.button !== 0) { return; }
        var redimensiona = e.target.classList.contains("firma-asa");
        var area = this.escenario.getBoundingClientRect();
        var inicio = {
            px: e.clientX, py: e.clientY,
            x: this.valor(codigo, "x"), y: this.valor(codigo, "y"),
            ancho: this.valor(codigo, "ancho"), alto: this.valor(codigo, "alto")
        };
        caja.setPointerCapture(e.pointerId);
        caja.classList.add("moviendo");
        e.preventDefault();

        function mover(ev) {
            var dx = (ev.clientX - inicio.px) / area.width * 100;
            var dy = (ev.clientY - inicio.py) / area.height * 100;
            if (redimensiona) {
                self.poner(codigo, "ancho", acotar(inicio.ancho + dx, ANCHO_MIN, 100 - inicio.x));
                self.poner(codigo, "alto", acotar(inicio.alto + dy, ALTO_MIN, 100 - inicio.y));
            } else {
                self.poner(codigo, "x", acotar(inicio.x + dx, 0, 100 - inicio.ancho));
                self.poner(codigo, "y", acotar(inicio.y + dy, 0, 100 - inicio.alto));
            }
            self.dibujarCajas();
        }
        function soltar() {
            caja.classList.remove("moviendo");
            caja.removeEventListener("pointermove", mover);
            caja.removeEventListener("pointerup", soltar);
            caja.removeEventListener("pointercancel", soltar);
        }
        caja.addEventListener("pointermove", mover);
        caja.addEventListener("pointerup", soltar);
        caja.addEventListener("pointercancel", soltar);
    };

    // Flechas: mueven el recuadro; con Ctrl cambian su tamaño. Con Shift el paso es más grande.
    Editor.prototype.teclado = function (e, codigo) {
        var paso = e.shiftKey ? 2 : 0.5;
        var dx = { ArrowLeft: -paso, ArrowRight: paso }[e.key] || 0;
        var dy = { ArrowUp: -paso, ArrowDown: paso }[e.key] || 0;
        if (!dx && !dy) { return; }
        e.preventDefault();
        var x = this.valor(codigo, "x"), y = this.valor(codigo, "y");
        var ancho = this.valor(codigo, "ancho"), alto = this.valor(codigo, "alto");
        if (e.ctrlKey) {
            this.poner(codigo, "ancho", acotar(ancho + dx, ANCHO_MIN, 100 - x));
            this.poner(codigo, "alto", acotar(alto + dy, ALTO_MIN, 100 - y));
        } else {
            this.poner(codigo, "x", acotar(x + dx, 0, 100 - ancho));
            this.poner(codigo, "y", acotar(y + dy, 0, 100 - alto));
        }
        this.dibujarCajas();
    };

    Editor.prototype.avisar = function (texto) {
        if (this.aviso) { this.aviso.textContent = texto; }
    };

    Editor.prototype.sinRecibo = function (texto) {
        this.escenario.style.aspectRatio = "210 / 297";
        this.escenario.classList.add("sin-recibo");
        this.avisar(texto);
    };

    Editor.prototype.cargarRecibo = function () {
        var self = this, url = this.raiz.dataset.modelo;
        if (!url) { this.sinRecibo("Todavía no hay un modelo de recibo cargado."); return; }
        this.avisar("Cargando tu recibo…");
        cargarPdfJs().then(function (lib) {
            return lib.getDocument(url).promise;
        }).then(function (pdf) {
            self.pdf = pdf;
            return self.dibujarPagina();
        }).catch(function () {
            self.sinRecibo("No pudimos mostrar tu recibo acá. Igual podés ubicar la firma con los números de abajo.");
        });
    };

    Editor.prototype.dibujarPagina = function () {
        var self = this;
        if (!this.pdf) { return Promise.resolve(); }
        var elegida = this.pagina ? this.pagina.value : "primera";
        var numero = elegida === "ultima" ? this.pdf.numPages : 1;
        return this.pdf.getPage(numero).then(function (pagina) {
            var base = pagina.getViewport({ scale: 1 });
            var ancho = self.escenario.clientWidth || base.width;
            var vista = pagina.getViewport({ scale: ancho / base.width * (window.devicePixelRatio || 1) });
            self.canvas.width = vista.width;
            self.canvas.height = vista.height;
            self.escenario.style.aspectRatio = base.width + " / " + base.height;
            self.escenario.classList.remove("sin-recibo");
            var texto = elegida === "todas"
                ? "Mostramos la primera página: la firma va en el mismo lugar en todas."
                : "Estás viendo la " + (elegida === "ultima" ? "última" : "primera") + " página de tu recibo.";
            self.avisar(self.soloLectura ? "" : texto);
            return pagina.render({ canvasContext: self.canvas.getContext("2d"), viewport: vista }).promise;
        });
    };

    function iniciar(raiz) {
        if (raiz.dataset.iniciado) { return; }
        raiz.dataset.iniciado = "1";
        new Editor(raiz);
    }

    function iniciarTodos() {
        document.querySelectorAll(".firma-editor").forEach(function (raiz) {
            var plegable = raiz.dataset.diferido ? raiz.closest("details") : null;
            if (!plegable) { iniciar(raiz); return; }
            // En un desplegable cerrado no hay ancho para dibujar: se inicia al abrirlo.
            if (plegable.open) { iniciar(raiz); return; }
            plegable.addEventListener("toggle", function () { if (plegable.open) { iniciar(raiz); } });
        });
    }

    window.NapsisFirma = { iniciarTodos: iniciarTodos };
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", iniciarTodos);
    } else {
        iniciarTodos();
    }
})();
