from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
import json

from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from automatizacion.actores import Actor
from automatizacion.congelada import como_documento as congelada_como_documento
from automatizacion.models import ConfiguracionCongelada
from catalog.models import TipoLicencia, TipoNovedad
from clients.models import Cliente, ComentarioInterno, Implementacion, Modulo, UbicacionFirma
from clients.services import (
    COLUMNAS_ORDENABLES,
    filtrar_y_ordenar_implementaciones,
    resumen_implementacion,
)
from employees.forms import EmpleadoForm, ImportarArchivoForm
from employees.services import ArchivoInvalido, formatear_cuil, generar_nomina_xlsx
from onboarding import acciones
from onboarding import services as onboarding_services
from onboarding.forms import (
    CondicionesForm,
    DocumentosLegajoForm,
    FirmaForm,
    ImplementacionDatosForm,
    LicenciasNovedadesForm,
    LiquidacionesForm,
    RolFormSet,
    SucursalFormSet,
)

from . import services as cuentas
from .forms import ImplementadorAltaForm, ImplementadorEdicionForm
from .permisos import admin_requerido
from .reportes import generar_reporte_implementaciones_xlsx


def _avisar_credenciales(request, titulo, username, password):
    """Muestra una única vez las credenciales recién generadas (no se vuelven a ver)."""
    messages.success(
        request,
        f"{titulo} — usuario: {username} / contraseña: {password} (anotala ahora, no se vuelve a mostrar).",
    )


def _mostrar(request, resultado):
    """Muestra lo que dejó una acción: sus avisos y, si no se pudo hacer, sus errores."""
    resultado.mostrar(request)
    for error in resultado.errores:
        messages.error(request, error)
    return resultado


def _base_url(request):
    return request.build_absolute_uri("/")


def _implementador_elegido(request):
    """El implementador elegido en el formulario (campo implementador_id). Si no vino, o no
    es una cuenta activa del equipo, queda asignada a quien la está creando."""
    elegido = request.POST.get("implementador_id", "")
    if elegido.isdigit():
        encontrado = cuentas.asignables().filter(pk=elegido).first()
        if encontrado:
            return encontrado
    return request.user


def _sort_links(request):
    """Arma, para cada columna ordenable, la URL que alterna asc/desc conservando los demás filtros."""
    ordenar_actual = request.GET.get("ordenar", "creado")
    direccion_actual = request.GET.get("direccion", "desc")

    links = {}
    for columna in COLUMNAS_ORDENABLES:
        params = request.GET.copy()
        es_columna_activa = ordenar_actual == columna
        params["ordenar"] = columna
        params["direccion"] = "desc" if (es_columna_activa and direccion_actual == "asc") else "asc"
        links[columna] = {
            "url": f"?{params.urlencode()}",
            "activa": es_columna_activa,
            "direccion": direccion_actual if es_columna_activa else None,
        }
    return links


def _alta_de_implementacion(request, condiciones_form):
    """Crea la implementación (y la empresa, si es nueva) con lo que llegó del formulario de
    alta. Devuelve (implementacion, errores): si algo no pasó la validación la implementación
    es None y `errores` dice por qué (se muestran dentro del modal del alta)."""
    if not condiciones_form.is_valid():
        detalle = " ".join(e for lista in condiciones_form.errors.values() for e in lista)
        return None, [f"Revisá las condiciones del proceso: {detalle}"]

    cliente_id = request.POST.get("cliente_id")
    cliente, datos_cliente = None, {}
    if cliente_id and cliente_id.isdigit():
        cliente = Cliente.objects.filter(pk=cliente_id).first()
    else:
        datos_cliente = {
            "nombre": request.POST.get("nombre", ""), "razon_social": request.POST.get("razon_social", ""),
            "cuits": request.POST.get("cuits", ""),
        }

    resultado = acciones.crear_implementacion(
        Actor.de_usuario(request.user), cliente=cliente, datos_cliente=datos_cliente,
        username=request.POST.get("username", ""), mail_cliente=request.POST.get("mail_cliente", ""),
        implementador=_implementador_elegido(request), creado_por=request.user,
        modulo_ids={int(v) for v in request.POST.getlist("modulos") if v.isdigit()},
        modulos_editables=bool(request.POST.get("modulos_editables")), condiciones=condiciones_form,
        base_url=_base_url(request),
    )
    if not resultado.ok:
        return None, resultado.errores
    resultado.mostrar(request)
    return resultado.implementacion, []


@staff_member_required(login_url="login")
def home(request):
    es_alta = request.method == "POST" and request.POST.get("accion") == "crear_implementacion"
    condiciones_form = CondicionesForm(request.POST if es_alta else None)
    errores_alta = []
    if es_alta:
        implementacion, errores_alta = _alta_de_implementacion(request, condiciones_form)
        if implementacion:
            return redirect("dashboard:implementacion_detalle", pk=implementacion.pk)

    # El alta vive en un modal. Si falló, se reabre mostrando el motivo y conservando lo que
    # el usuario ya había escrito (no tiene que volver a cargar todo).
    alta = {
        "abrir": bool(errores_alta),
        "errores": errores_alta,
        "valores": request.POST if es_alta else {},
        "modulos": set(request.POST.getlist("modulos")) if es_alta else set(),
        "editables": bool(request.POST.get("modulos_editables")) if es_alta else True,
    }

    clientes_existentes = Cliente.objects.order_by("nombre")
    implementaciones = filtrar_y_ordenar_implementaciones(
        Implementacion.objects.select_related("cliente", "implementador_asignado"), request.GET
    )

    return render(
        request, "dashboard/home.html",
        {
            "implementaciones": implementaciones,
            "clientes_existentes": clientes_existentes,
            "asignables": cuentas.asignables(),
            "condiciones_form": condiciones_form,
            "alta": alta,
            "modulos": Modulo.objects.all(),
            "estados_choices": Implementacion.opciones_de_filtro_de_estado(),
            "filtros_aplicados": request.GET,
            "sort_links": _sort_links(request),
        },
    )


@staff_member_required(login_url="login")
def cliente_detalle(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    actor = Actor.de_usuario(request.user)

    if request.method == "POST" and request.POST.get("accion") == "regenerar_acceso":
        _mostrar(request, acciones.entregar_acceso(
            actor, cliente, request.POST.get("username", ""), request.POST.get("mail_cliente", ""),
            base_url=_base_url(request),
        ))
        return redirect("dashboard:cliente_detalle", pk=pk)

    if request.method == "POST" and request.POST.get("accion") == "enviar_invitacion":
        _mostrar(request, acciones.invitar_cliente(actor, cliente, base_url=_base_url(request)))
        return redirect("dashboard:cliente_detalle", pk=pk)

    implementaciones = cliente.implementaciones.order_by("-creado")
    return render(
        request, "dashboard/cliente_detalle.html",
        {"cliente": cliente, "implementaciones": implementaciones},
    )


# --- Ficha de la implementación: cada acción del formulario es una función ------------------
#
# Una acción devuelve un redirect (se hizo), un diccionario con el formulario que falló (se vuelve a
# mostrar la página con sus errores) o None (acción desconocida: no pasa nada).


def _empleado_del_panel(implementacion, empleado_id):
    return implementacion.empleados.filter(pk=empleado_id).first() if str(empleado_id).isdigit() else None


def _volver(implementacion):
    return redirect("dashboard:implementacion_detalle", pk=implementacion.pk)


def _accion_actualizar_datos(request, implementacion, actor):
    form = ImplementacionDatosForm(request.POST, request.FILES, instance=implementacion)
    if form.is_valid():
        onboarding_services.guardar_datos_contacto(implementacion, form, actor)
        messages.success(request, "Datos de contacto actualizados.")
        return _volver(implementacion)
    return {"datos_form": form}


def _accion_actualizar_modulos(request, implementacion, actor):
    modulo_ids = {int(v) for v in request.POST.getlist("modulos") if v.isdigit()}
    onboarding_services.guardar_modulos(implementacion, Modulo.objects.all(), modulo_ids, actor)
    implementacion.modulos_editables_por_cliente = bool(request.POST.get("modulos_editables"))
    implementacion.save(update_fields=["modulos_editables_por_cliente"])
    return _volver(implementacion)


def _accion_actualizar_roles(request, implementacion, actor):
    formset = RolFormSet(request.POST, prefix="roles")
    if formset.is_valid():
        onboarding_services.guardar_roles(implementacion, formset, actor)
        messages.success(request, "Roles actualizados.")
        return _volver(implementacion)
    return {"roles_formset": formset}


def _accion_actualizar_sucursales(request, implementacion, actor):
    formset = SucursalFormSet(request.POST, prefix="sucursales")
    if formset.is_valid():
        onboarding_services.guardar_sucursales(implementacion, formset, actor)
        messages.success(request, "Sucursales actualizadas.")
        return _volver(implementacion)
    return {"sucursales_formset": formset}


def _accion_actualizar_licencias_novedades(request, implementacion, actor):
    licencias_qs = TipoLicencia.objects.all()
    novedades_qs = TipoNovedad.objects.all()
    form = LicenciasNovedadesForm(
        request.POST, licencias_qs=licencias_qs, novedades_qs=novedades_qs,
        estado_por_licencia=onboarding_services.estado_actual_licencias(implementacion),
        estado_por_novedad=onboarding_services.estado_actual_novedades(implementacion),
    )
    if form.is_valid():
        onboarding_services.guardar_licencias_y_novedades(implementacion, form, licencias_qs, novedades_qs, actor)
        messages.success(request, "Licencias y novedades actualizadas.")
        return _volver(implementacion)
    return {"licencias_novedades_form": form}


def _accion_actualizar_documentos(request, implementacion, actor):
    todos_qs = onboarding_services.tipos_documento_disponibles(implementacion)
    form = DocumentosLegajoForm(
        request.POST, tipos_qs=todos_qs,
        estado_por_tipo=onboarding_services.estado_actual_documentos(implementacion),
    )
    if form.is_valid():
        onboarding_services.guardar_documentos(implementacion, form, todos_qs, actor)
        messages.success(request, "Documentos de legajo actualizados.")
        return _volver(implementacion)
    return {"documentos_form": form}


def _accion_actualizar_liquidaciones(request, implementacion, actor):
    form = LiquidacionesForm(request.POST, implementacion=implementacion)
    if form.is_valid():
        onboarding_services.guardar_liquidaciones(implementacion, form.cleaned_data["tipos_liquidacion"], actor)
        messages.success(request, "Tipos de liquidación actualizados.")
        return _volver(implementacion)
    return {"liquidaciones_form": form}


def _accion_validar_firma(request, implementacion, actor):
    _mostrar(request, acciones.validar_firma(actor, implementacion))
    return _volver(implementacion)


def _accion_observar_firma(request, implementacion, actor):
    _mostrar(request, acciones.observar_firma(
        actor, implementacion, request.POST.getlist("motivos"), request.POST.get("comentario", ""),
        base_url=_base_url(request),
    ))
    return _volver(implementacion)


def _accion_corregir_firma(request, implementacion, actor):
    firma = implementacion.firma
    form = FirmaForm(request.POST, request.FILES, firma=firma)
    if form.is_valid():
        onboarding_services.guardar_firma(
            implementacion, actor, pagina=form.cleaned_data["pagina"], geometria=form.geometria(),
            imagen=form.cleaned_data["imagen"],
        )
        messages.success(request, "Firma corregida y validada.")
        return _volver(implementacion)
    return {"firma_form": form}


def _accion_agregar_empleado(request, implementacion, actor):
    empleado_form = EmpleadoForm(request.POST, implementacion=implementacion)
    if onboarding_services.agregar_empleado(implementacion, empleado_form, actor):
        messages.success(request, "Empleado agregado.")
        return _volver(implementacion)
    return {"empleado_form": empleado_form}


def _accion_editar_empleado(request, implementacion, actor):
    empleado = _empleado_del_panel(implementacion, request.POST.get("empleado_id"))
    if not empleado:
        return _volver(implementacion)
    form = EmpleadoForm(request.POST, instance=empleado, implementacion=implementacion)
    if onboarding_services.editar_empleado(implementacion, form, actor):
        messages.success(request, "Empleado actualizado.")
        return _volver(implementacion)
    return {"empleado_edit_form": form, "empleado_editando": empleado}


def _accion_eliminar_empleado(request, implementacion, actor):
    onboarding_services.eliminar_empleado(implementacion, request.POST.get("empleado_id"), actor)
    messages.info(request, "Empleado eliminado.")
    return _volver(implementacion)


def _accion_importar_empleados(request, implementacion, actor):
    import_form = ImportarArchivoForm(request.POST, request.FILES)
    if not import_form.is_valid():
        return {"import_form": import_form}
    try:
        filas, errores, advertencias = onboarding_services.importar_archivo_empleados(
            implementacion, import_form.cleaned_data["archivo"], actor
        )
    except ArchivoInvalido as error:
        import_form.add_error("archivo", str(error))
        return {"import_form": import_form}
    for nivel, texto in onboarding_services.resumen_importacion(filas, errores, advertencias):
        messages.add_message(request, nivel, texto)
    if errores:
        detalle = "; ".join(f"fila {e['fila']}: {e['mensaje']}" for e in errores[:5])
        messages.warning(request, "Filas rechazadas: " + detalle + (" ..." if len(errores) > 5 else ""))
    return _volver(implementacion)


def _accion_actualizar_condiciones(request, implementacion, actor):
    form = CondicionesForm(request.POST, implementacion=implementacion)
    if form.is_valid():
        onboarding_services.guardar_condiciones(implementacion, form, actor)
        messages.success(request, "Condiciones del proceso actualizadas.")
        return _volver(implementacion)
    return {"condiciones_form": form}


def _accion_reasignar(request, implementacion, actor):
    elegido = request.POST.get("implementador_id", "")
    nuevo = cuentas.asignables().filter(pk=elegido).first() if elegido.isdigit() else None
    if nuevo:
        _mostrar(request, acciones.reasignar(actor, implementacion, nuevo))
    return _volver(implementacion)


def _accion_regenerar_link(request, implementacion, actor):
    _mostrar(request, acciones.reabrir(actor, implementacion))
    return _volver(implementacion)


def _accion_anular(request, implementacion, actor):
    _mostrar(request, acciones.anular(actor, implementacion))
    return _volver(implementacion)


def _accion_marcar_cumplida(request, implementacion, actor):
    _mostrar(request, acciones.marcar_cumplida(actor, implementacion, base_url=_base_url(request)))
    return _volver(implementacion)


def _accion_aprobar_para_configurar(request, implementacion, actor):
    _mostrar(request, acciones.aprobar_para_configurar(actor, implementacion))
    return _volver(implementacion)


def _accion_devolver_al_cliente(request, implementacion, actor):
    observaciones = {
        codigo: request.POST.get(f"obs_{codigo}", "") for codigo in onboarding_services.CODIGO_DE_PASO.values()
    }
    _mostrar(request, acciones.devolver_al_cliente(
        actor, implementacion, request.POST.get("motivo", ""), observaciones, base_url=_base_url(request),
    ))
    return _volver(implementacion)


def _accion_agregar_comentario(request, implementacion, actor):
    _mostrar(request, acciones.agregar_comentario(
        actor, implementacion, request.POST.get("texto", ""), autor=request.user,
    ))
    return _volver(implementacion)


def _accion_atender_revision(request, implementacion, actor):
    _mostrar(request, acciones.atender_revision(actor, implementacion))
    return _volver(implementacion)


def _accion_actualizar_fecha_productivo(request, implementacion, actor):
    # El equipo puede poner cualquier fecha (sin el mínimo que se le exige al cliente).
    onboarding_services.guardar_fecha_implementacion(
        implementacion, parse_date(request.POST.get("fecha_salida_productivo", "")), actor,
    )
    return _volver(implementacion)


def _accion_regenerar_acceso(request, implementacion, actor):
    _mostrar(request, acciones.entregar_acceso(
        actor, implementacion.cliente, request.POST.get("username", ""), request.POST.get("mail_cliente", ""),
        base_url=_base_url(request), implementacion=implementacion,
    ))
    return _volver(implementacion)


def _accion_enviar_invitacion(request, implementacion, actor):
    _mostrar(request, acciones.invitar_cliente(
        actor, implementacion.cliente, implementacion=implementacion, base_url=_base_url(request),
    ))
    return _volver(implementacion)


ACCIONES_DE_LA_FICHA = {
    "actualizar_datos": _accion_actualizar_datos,
    "actualizar_modulos": _accion_actualizar_modulos,
    "actualizar_roles": _accion_actualizar_roles,
    "actualizar_sucursales": _accion_actualizar_sucursales,
    "actualizar_licencias_novedades": _accion_actualizar_licencias_novedades,
    "actualizar_documentos": _accion_actualizar_documentos,
    "actualizar_liquidaciones": _accion_actualizar_liquidaciones,
    "validar_firma": _accion_validar_firma,
    "observar_firma": _accion_observar_firma,
    "corregir_firma": _accion_corregir_firma,
    "agregar_empleado": _accion_agregar_empleado,
    "editar_empleado": _accion_editar_empleado,
    "eliminar_empleado": _accion_eliminar_empleado,
    "importar_empleados": _accion_importar_empleados,
    "actualizar_condiciones": _accion_actualizar_condiciones,
    "reasignar": _accion_reasignar,
    "regenerar_link": _accion_regenerar_link,
    "anular": _accion_anular,
    "marcar_cumplida": _accion_marcar_cumplida,
    "aprobar_para_configurar": _accion_aprobar_para_configurar,
    "devolver_al_cliente": _accion_devolver_al_cliente,
    "atender_revision": _accion_atender_revision,
    "agregar_comentario": _accion_agregar_comentario,
    "actualizar_fecha_productivo": _accion_actualizar_fecha_productivo,
    "regenerar_acceso": _accion_regenerar_acceso,
    "enviar_invitacion": _accion_enviar_invitacion,
}


# Estas acciones sacan la validación porque eso es justo lo que hacen: no hace falta avisarlo aparte.
ACCIONES_QUE_SACAN_LA_VALIDACION_A_PROPOSITO = {"devolver_al_cliente", "observar_firma", "regenerar_link"}


def _manejar_accion_implementacion(request, implementacion):
    """Procesa el POST de implementacion_detalle. Devuelve un redirect si la acción fue manejada, un
    diccionario con el formulario que falló (hay que renderizar la página con sus errores) o None."""
    accion = request.POST.get("accion")
    manejador = ACCIONES_DE_LA_FICHA.get(accion)
    if manejador is None:
        return None
    estaba_validada = implementacion.validada_en is not None
    resultado = manejador(request, implementacion, Actor.de_usuario(request.user))
    if estaba_validada and accion not in ACCIONES_QUE_SACAN_LA_VALIDACION_A_PROPOSITO:
        implementacion.refresh_from_db(fields=["validada_en"])
        if implementacion.validada_en is None:
            messages.warning(
                request,
                "La documentación estaba validada y volvió a «Pendiente de validación» porque cambiaste algo de lo "
                "que se configura: hay que volver a validarla (la configuración congelada anterior queda como historia).",
            )
    return resultado


@staff_member_required(login_url="login")
def implementacion_detalle(request, pk):
    implementacion = get_object_or_404(
        Implementacion.objects.select_related("cliente").prefetch_related(
            "modulos__modulo", "roles", "sucursales", "licencias__tipo_licencia",
            "novedades__tipo_novedad", "documentos_legajo__tipo_documento", "empleados",
        ),
        pk=pk,
    )

    formularios_con_error = {}
    if request.method == "POST":
        resultado = _manejar_accion_implementacion(request, implementacion)
        if resultado is None:
            return redirect("dashboard:implementacion_detalle", pk=pk)
        if hasattr(resultado, "status_code"):  # es un redirect
            return resultado
        formularios_con_error = resultado

    # Edición de un empleado: ?editar_empleado=<id> abre el formulario con sus datos (o vuelve con
    # los errores si se intentó guardar algo inválido).
    empleado_editando = formularios_con_error.get("empleado_editando")
    empleado_edit_form = formularios_con_error.get("empleado_edit_form")
    if empleado_editando is None and request.method == "GET":
        empleado_editando = _empleado_del_panel(implementacion, request.GET.get("editar_empleado"))
        if empleado_editando:
            empleado_edit_form = EmpleadoForm(instance=empleado_editando, implementacion=implementacion)

    roles_iniciales = [
        {"rol": r.rol, "apellido_nombre": r.apellido_nombre, "cuil": formatear_cuil(r.cuil), "mail": r.mail}
        for r in implementacion.roles.all()
    ]
    sucursales_iniciales = [
        {
            "nombre": s.nombre, "calle": s.calle, "altura": s.altura, "piso_depto": s.piso_depto,
            "codigo_postal": s.codigo_postal, "localidad": s.localidad,
            "entre_calles": s.entre_calles, "observaciones": s.observaciones,
        }
        for s in implementacion.sucursales.all()
    ]
    licencias_qs = TipoLicencia.objects.all()
    novedades_qs = TipoNovedad.objects.all()
    tipos_documento_qs = onboarding_services.tipos_documento_disponibles(implementacion)

    licencias_novedades_form = formularios_con_error.get("licencias_novedades_form") or LicenciasNovedadesForm(
        licencias_qs=licencias_qs, novedades_qs=novedades_qs,
        estado_por_licencia=onboarding_services.estado_actual_licencias(implementacion),
        estado_por_novedad=onboarding_services.estado_actual_novedades(implementacion),
    )
    documentos_form = formularios_con_error.get("documentos_form") or DocumentosLegajoForm(
        tipos_qs=tipos_documento_qs, estado_por_tipo=onboarding_services.estado_actual_documentos(implementacion)
    )

    contexto = resumen_implementacion(implementacion)
    contexto.update({
        "link_url": request.build_absolute_uri(implementacion.get_absolute_url()),
        "rondas": implementacion.rondas.all(),
        "comentarios": implementacion.comentarios.all(),
        "max_largo_comentario": ComentarioInterno.MAX_LARGO,
        "congeladas": implementacion.congeladas.order_by("-version"),
        "congelada_vigente": (
            implementacion.congeladas.order_by("-version").first() if implementacion.validada_en else None
        ),
        "pendientes_de_validacion": (
            onboarding_services.pendientes_de_validacion(implementacion)
            if implementacion.enviado and not implementacion.validada_en else []
        ),
        "pasos_observables": [
            (onboarding_services.CODIGO_DE_PASO[n], onboarding_services.TITULOS_PASO[n])
            for n in onboarding_services.pasos_activos(implementacion) if n != onboarding_services.PASO_REVISION
        ],
        "asignables": cuentas.asignables(),
        "condiciones_form": formularios_con_error.get("condiciones_form")
        or CondicionesForm(implementacion=implementacion),
        "datos_form": formularios_con_error.get("datos_form") or ImplementacionDatosForm(instance=implementacion),
        "roles_formset": formularios_con_error.get("roles_formset") or RolFormSet(initial=roles_iniciales, prefix="roles"),
        "sucursales_formset": formularios_con_error.get("sucursales_formset") or SucursalFormSet(initial=sucursales_iniciales, prefix="sucursales"),
        "licencias_rows": [(licencia, licencias_novedades_form[f"licencia_{licencia.id}_activo"]) for licencia in licencias_qs],
        "novedades_rows": [(n, licencias_novedades_form[f"novedad_{n.id}_activo"]) for n in novedades_qs],
        "licencias_novedades_form": licencias_novedades_form,
        "documentos_rows": [(t, documentos_form[f"tipo_{t.id}_activo"]) for t in tipos_documento_qs],
        "documentos_form": documentos_form,
        **onboarding_services.contexto_del_editor_de_firma(
            implementacion, implementacion.firma, formularios_con_error.get("firma_form") or FirmaForm(firma=implementacion.firma),
        ),
        "motivos_de_firma": UbicacionFirma.MOTIVOS,
        "usa_recibo_digital": implementacion.usa_modulo(Modulo.RECIBO_DIGITAL),
        "liquidaciones_form": formularios_con_error.get("liquidaciones_form") or LiquidacionesForm(implementacion=implementacion),
        "empleado_form": formularios_con_error.get("empleado_form") or EmpleadoForm(implementacion=implementacion),
        "empleado_editando": empleado_editando,
        "empleado_edit_form": empleado_edit_form,
        "import_form": formularios_con_error.get("import_form") or ImportarArchivoForm(),
    })
    return render(request, "dashboard/implementacion_detalle.html", contexto)


@staff_member_required(login_url="login")
def descargar_congelada(request, pk, version):
    """La configuración congelada de una versión, como un único .json (solo el equipo)."""
    congelada = get_object_or_404(ConfiguracionCongelada, implementacion_id=pk, version=version)
    respuesta = HttpResponse(
        json.dumps(congelada_como_documento(congelada), ensure_ascii=False, indent=2, sort_keys=True),
        content_type="application/json; charset=utf-8",
    )
    respuesta["Content-Disposition"] = f'attachment; filename="configuracion_{pk}_v{version}.json"'
    return respuesta


@staff_member_required(login_url="login")
def descargar_nomina(request, pk):
    implementacion = get_object_or_404(Implementacion, pk=pk)
    empleados = implementacion.empleados.select_related("reporta_a", "aprobador").all()
    buffer = generar_nomina_xlsx(empleados)
    nombre_archivo = f"nomina_{implementacion.cliente.nombre}.xlsx".replace(" ", "_")
    return FileResponse(
        buffer, as_attachment=True, filename=nombre_archivo,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@staff_member_required(login_url="login")
def exportar_implementaciones(request):
    """Descarga un .xlsx con todas las implementaciones (botón "Exportar" al pie del panel)."""
    nombre = f"implementaciones_{timezone.localdate():%Y-%m-%d}.xlsx"
    return FileResponse(
        generar_reporte_implementaciones_xlsx(), as_attachment=True, filename=nombre,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# --- Rol Admin: gestión de implementadores -------------------------------------


@admin_requerido
def implementadores_lista(request):
    form = ImplementadorAltaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario, password = cuentas.crear_implementador(**form.cleaned_data)
        _avisar_credenciales(request, "Implementador creado", usuario.username, password)
        return redirect("dashboard:implementadores")
    return render(
        request, "dashboard/implementadores.html",
        {"implementadores": cuentas.implementadores(), "form": form},
    )


@admin_requerido
def implementador_detalle(request, pk):
    usuario = get_object_or_404(cuentas.implementadores(), pk=pk)
    form = ImplementadorEdicionForm(instance=usuario)

    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "guardar":
            form = ImplementadorEdicionForm(request.POST, instance=usuario)
            if form.is_valid():
                form.save()
                messages.success(request, "Datos actualizados.")
                return redirect("dashboard:implementador_detalle", pk=pk)
        elif accion == "resetear_password":
            password = cuentas.resetear_password(usuario)
            _avisar_credenciales(request, "Nueva contraseña generada", usuario.username, password)
            return redirect("dashboard:implementador_detalle", pk=pk)
        elif accion == "dar_de_baja":
            cuentas.dar_de_baja(usuario)
            messages.info(request, f"{usuario.username} quedó dado de baja: ya no puede ingresar.")
            return redirect("dashboard:implementador_detalle", pk=pk)
        elif accion == "reactivar":
            cuentas.reactivar(usuario)
            messages.success(request, f"{usuario.username} volvió a estar activo.")
            return redirect("dashboard:implementador_detalle", pk=pk)

    return render(request, "dashboard/implementador_detalle.html", {"usuario": usuario, "form": form})
