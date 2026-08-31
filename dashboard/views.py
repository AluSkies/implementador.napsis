from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date

from catalog.models import TipoLicencia, TipoNovedad
from clients.models import Cliente, Implementacion, ImplementacionModulo, Modulo
from clients.services import (
    COLUMNAS_ORDENABLES,
    crear_o_resetear_acceso,
    filtrar_y_ordenar_implementaciones,
    guardar_version,
    resumen_implementacion,
)
from employees.forms import EmpleadoForm, ImportarArchivoForm
from employees.services import generar_nomina_xlsx
from onboarding import services as onboarding_services
from onboarding.forms import (
    DocumentosLegajoForm,
    ImplementacionDatosForm,
    LicenciasNovedadesForm,
    RolFormSet,
    SucursalFormSet,
)


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


@staff_member_required(login_url="login")
def home(request):
    if request.method == "POST" and request.POST.get("accion") == "crear_implementacion":
        cliente_id = request.POST.get("cliente_id")
        nombre_nuevo = request.POST.get("nombre", "").strip()
        cuits_nuevo = request.POST.get("cuits", "").strip()
        modulo_ids = {int(v) for v in request.POST.getlist("modulos")}
        editable = bool(request.POST.get("modulos_editables"))

        cliente = None
        if cliente_id:
            cliente = Cliente.objects.filter(pk=cliente_id).first()
        elif nombre_nuevo:
            cliente = Cliente.objects.create(nombre=nombre_nuevo, cuits=cuits_nuevo)

        if cliente:
            if not cliente.usuario:
                username_deseado = request.POST.get("username", "").strip()
                username, password = crear_o_resetear_acceso(cliente, username_deseado)
                messages.success(
                    request,
                    f"Acceso creado para el cliente — usuario: {username} / contraseña: {password} "
                    "(anotala ahora, no se vuelve a mostrar).",
                )
            implementacion = Implementacion.objects.create(
                cliente=cliente, creado_por=request.user, modulos_editables_por_cliente=editable
            )
            ImplementacionModulo.objects.bulk_create(
                ImplementacionModulo(implementacion=implementacion, modulo=modulo, activo=modulo.id in modulo_ids)
                for modulo in Modulo.objects.all()
            )
            return redirect("dashboard:implementacion_detalle", pk=implementacion.pk)

    clientes_existentes = Cliente.objects.order_by("nombre")
    implementaciones = filtrar_y_ordenar_implementaciones(
        Implementacion.objects.select_related("cliente"), request.GET
    )

    return render(
        request, "dashboard/home.html",
        {
            "implementaciones": implementaciones,
            "clientes_existentes": clientes_existentes,
            "modulos": Modulo.objects.all(),
            "estados_choices": Implementacion.VISUAL_LABELS.items(),
            "filtros_aplicados": request.GET,
            "sort_links": _sort_links(request),
        },
    )


@staff_member_required(login_url="login")
def cliente_detalle(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)

    if request.method == "POST" and request.POST.get("accion") == "regenerar_acceso":
        username_deseado = request.POST.get("username", "").strip()
        username, password = crear_o_resetear_acceso(cliente, username_deseado)
        messages.success(
            request,
            f"Nueva contraseña generada — usuario: {username} / contraseña: {password} "
            "(anotala ahora, no se vuelve a mostrar).",
        )
        return redirect("dashboard:cliente_detalle", pk=pk)

    implementaciones = cliente.implementaciones.order_by("-creado")
    return render(
        request, "dashboard/cliente_detalle.html",
        {"cliente": cliente, "implementaciones": implementaciones},
    )


def _manejar_accion_implementacion(request, implementacion):
    """Procesa el POST de implementacion_detalle. Devuelve un redirect si la acción
    fue manejada, o None si hay que renderizar la página (con errores de formulario, por ej.)."""
    accion = request.POST.get("accion")
    pk = implementacion.pk
    editado_por = request.user.get_username()

    if accion == "actualizar_datos":
        form = ImplementacionDatosForm(request.POST, request.FILES, instance=implementacion)
        if form.is_valid():
            onboarding_services.guardar_datos_contacto(implementacion, form, editado_por)
            messages.success(request, "Datos de contacto actualizados.")
            return redirect("dashboard:implementacion_detalle", pk=pk)
        return {"datos_form": form}

    if accion == "actualizar_modulos":
        modulo_ids = {int(v) for v in request.POST.getlist("modulos")}
        onboarding_services.guardar_modulos(implementacion, Modulo.objects.all(), modulo_ids, editado_por)
        implementacion.modulos_editables_por_cliente = bool(request.POST.get("modulos_editables"))
        implementacion.save(update_fields=["modulos_editables_por_cliente"])
        return redirect("dashboard:implementacion_detalle", pk=pk)

    if accion == "actualizar_roles":
        formset = RolFormSet(request.POST, prefix="roles")
        if formset.is_valid():
            onboarding_services.guardar_roles(implementacion, formset, editado_por)
            messages.success(request, "Roles actualizados.")
            return redirect("dashboard:implementacion_detalle", pk=pk)
        return {"roles_formset": formset}

    if accion == "actualizar_sucursales":
        formset = SucursalFormSet(request.POST, prefix="sucursales")
        if formset.is_valid():
            onboarding_services.guardar_sucursales(implementacion, formset, editado_por)
            messages.success(request, "Sucursales actualizadas.")
            return redirect("dashboard:implementacion_detalle", pk=pk)
        return {"sucursales_formset": formset}

    if accion == "actualizar_licencias_novedades":
        licencias_qs = TipoLicencia.objects.all()
        novedades_qs = TipoNovedad.objects.all()
        form = LicenciasNovedadesForm(
            request.POST, licencias_qs=licencias_qs, novedades_qs=novedades_qs,
            estado_por_licencia=onboarding_services.estado_actual_licencias(implementacion),
            estado_por_novedad=onboarding_services.estado_actual_novedades(implementacion),
        )
        if form.is_valid():
            onboarding_services.guardar_licencias_y_novedades(implementacion, form, licencias_qs, novedades_qs, editado_por)
            messages.success(request, "Licencias y novedades actualizadas.")
            return redirect("dashboard:implementacion_detalle", pk=pk)
        return {"licencias_novedades_form": form}

    if accion == "actualizar_documentos":
        todos_qs = onboarding_services.tipos_documento_disponibles(implementacion)
        form = DocumentosLegajoForm(
            request.POST, tipos_qs=todos_qs,
            estado_por_tipo=onboarding_services.estado_actual_documentos(implementacion),
        )
        if form.is_valid():
            onboarding_services.guardar_documentos(implementacion, form, todos_qs, editado_por)
            messages.success(request, "Documentos de legajo actualizados.")
            return redirect("dashboard:implementacion_detalle", pk=pk)
        return {"documentos_form": form}

    if accion == "agregar_empleado":
        empleado_form = EmpleadoForm(request.POST, implementacion=implementacion)
        if onboarding_services.agregar_empleado(implementacion, empleado_form, editado_por):
            messages.success(request, "Empleado agregado.")
            return redirect("dashboard:implementacion_detalle", pk=pk)
        return {"empleado_form": empleado_form}

    if accion == "eliminar_empleado":
        onboarding_services.eliminar_empleado(implementacion, request.POST.get("empleado_id"), editado_por)
        messages.info(request, "Empleado eliminado.")
        return redirect("dashboard:implementacion_detalle", pk=pk)

    if accion == "importar_empleados":
        import_form = ImportarArchivoForm(request.POST, request.FILES)
        if import_form.is_valid():
            filas, errores = onboarding_services.importar_archivo_empleados(
                implementacion, import_form.cleaned_data["archivo"], editado_por
            )
            if errores:
                messages.warning(
                    request,
                    f"Se importaron {len(filas)} empleados. {len(errores)} filas tuvieron errores y no se cargaron.",
                )
            else:
                messages.success(request, f"Se importaron {len(filas)} empleados correctamente.")
            return redirect("dashboard:implementacion_detalle", pk=pk)
        return {"import_form": import_form}

    if accion == "regenerar_link":
        implementacion.estado = Implementacion.ESTADO_PENDIENTE
        implementacion.paso_actual = 1
        implementacion.enviado = None
        implementacion.cancelada_en = None
        implementacion.cumplida_en = None
        implementacion.save(update_fields=["estado", "paso_actual", "enviado", "cancelada_en", "cumplida_en"])
        return redirect("dashboard:implementacion_detalle", pk=pk)

    if accion == "anular":
        implementacion.anular()
        return redirect("dashboard:implementacion_detalle", pk=pk)

    if accion == "marcar_cumplida":
        implementacion.marcar_cumplida()
        return redirect("dashboard:implementacion_detalle", pk=pk)

    if accion == "atender_revision":
        implementacion.marcar_revision_atendida()
        return redirect("dashboard:implementacion_detalle", pk=pk)

    if accion == "actualizar_fecha_productivo":
        guardar_version(implementacion, "fecha_implementacion", editado_por)
        implementacion.fecha_salida_productivo = parse_date(request.POST.get("fecha_salida_productivo", ""))
        implementacion.save(update_fields=["fecha_salida_productivo"])
        return redirect("dashboard:implementacion_detalle", pk=pk)

    if accion == "regenerar_acceso":
        username_deseado = request.POST.get("username", "").strip()
        username, password = crear_o_resetear_acceso(implementacion.cliente, username_deseado)
        messages.success(
            request,
            f"Nueva contraseña generada — usuario: {username} / contraseña: {password} "
            "(anotala ahora, no se vuelve a mostrar).",
        )
        return redirect("dashboard:implementacion_detalle", pk=pk)

    return None


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

    roles_iniciales = [
        {"rol": r.rol, "apellido_nombre": r.apellido_nombre, "cuil": r.cuil, "mail": r.mail}
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
        "datos_form": formularios_con_error.get("datos_form") or ImplementacionDatosForm(instance=implementacion),
        "roles_formset": formularios_con_error.get("roles_formset") or RolFormSet(initial=roles_iniciales, prefix="roles"),
        "sucursales_formset": formularios_con_error.get("sucursales_formset") or SucursalFormSet(initial=sucursales_iniciales, prefix="sucursales"),
        "licencias_rows": [(l, licencias_novedades_form[f"licencia_{l.id}_activo"]) for l in licencias_qs],
        "novedades_rows": [(n, licencias_novedades_form[f"novedad_{n.id}_activo"]) for n in novedades_qs],
        "licencias_novedades_form": licencias_novedades_form,
        "documentos_rows": [(t, documentos_form[f"tipo_{t.id}_activo"]) for t in tipos_documento_qs],
        "documentos_form": documentos_form,
        "empleado_form": formularios_con_error.get("empleado_form") or EmpleadoForm(implementacion=implementacion),
        "import_form": formularios_con_error.get("import_form") or ImportarArchivoForm(),
    })
    return render(request, "dashboard/implementacion_detalle.html", contexto)


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
