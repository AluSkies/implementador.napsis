from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
import logging

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date

from catalog.models import TipoLicencia, TipoNovedad
from clients.models import Cliente, Implementacion, Modulo
from clients.validators import normalizar_cuits
from clients.services import (
    COLUMNAS_ORDENABLES,
    crear_o_resetear_acceso,
    filtrar_y_ordenar_implementaciones,
    resumen_implementacion,
)
from employees.forms import EmpleadoForm, ImportarArchivoForm
from employees.services import generar_nomina_xlsx
from onboarding import services as onboarding_services
from onboarding.forms import (
    CondicionesForm,
    DocumentosLegajoForm,
    ImplementacionDatosForm,
    LicenciasNovedadesForm,
    RolFormSet,
    SucursalFormSet,
)

from notifications.services import enviar_invitacion, notificar_cliente_implementacion_cumplida

from . import services as cuentas
from .forms import ImplementadorAltaForm, ImplementadorEdicionForm
from .permisos import admin_requerido


def _avisar_credenciales(request, titulo, username, password):
    """Muestra una única vez las credenciales recién generadas (no se vuelven a ver)."""
    messages.success(
        request,
        f"{titulo} — usuario: {username} / contraseña: {password} (anotala ahora, no se vuelve a mostrar).",
    )


logger = logging.getLogger(__name__)


def _entregar_acceso(request, cliente, username_deseado, mail=""):
    """Crea o reinicia el acceso del cliente. Con un mail (y cuenta nueva) lo invita a crear
    su propia contraseña; si no, genera una y se la muestra al equipo una única vez."""
    era_nueva = not cliente.usuario
    username, password = crear_o_resetear_acceso(cliente, username_deseado, email=mail)
    if password:
        _avisar_credenciales(
            request, "Acceso creado para el cliente" if era_nueva else "Nueva contraseña generada", username, password,
        )
    else:
        _enviar_invitacion(request, cliente.usuario)


def _enviar_invitacion(request, usuario):
    """Manda el link para crear/cambiar la contraseña. Si el mail falla no se pierde nada:
    el aviso lo dice y se puede reenviar desde la ficha."""
    try:
        enviar_invitacion(usuario, request=request)
    except Exception:
        logger.exception("No se pudo enviar la invitación al usuario %s", usuario.pk)
        messages.warning(
            request,
            f"No se pudo enviar el mail a {usuario.email}. Usuario: {usuario.username}. "
            "Probá de nuevo desde la ficha con «Enviar mail para crear contraseña».",
        )
    else:
        messages.success(
            request, f"Le mandamos a {usuario.email} un mail para que cree su contraseña (usuario: {usuario.username}).",
        )


def _mail_valido(request):
    """El mail opcional del formulario de acceso: "" si no vino, None (y avisa) si es inválido."""
    mail = request.POST.get("mail_cliente", "").strip()
    if mail:
        try:
            validate_email(mail)
        except ValidationError:
            messages.error(request, "El mail no es válido.")
            return None
    return mail


def _invitar_desde_panel(request, cliente, implementacion=None):
    """Reenvía el link para crear/cambiar la contraseña al mail de la cuenta (o, si la cuenta
    no tiene, al de contacto de la implementación, que queda guardado en la cuenta)."""
    usuario = cliente.usuario
    if not usuario:
        messages.error(request, "El cliente todavía no tiene acceso creado.")
        return
    if not usuario.email and implementacion and implementacion.mail_contacto:
        usuario.email = implementacion.mail_contacto
        usuario.save(update_fields=["email"])
    if not usuario.email:
        messages.error(request, "No hay un mail cargado para este cliente: completalo en los datos de contacto.")
        return
    _enviar_invitacion(request, usuario)


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
    cliente_id = request.POST.get("cliente_id")
    nombre_nuevo = request.POST.get("nombre", "").strip()
    razon_social_nueva = request.POST.get("razon_social", "").strip()
    cuits_nuevo = request.POST.get("cuits", "").strip()
    modulo_ids = {int(v) for v in request.POST.getlist("modulos") if v.isdigit()}
    errores = []

    if not condiciones_form.is_valid():
        detalle = " ".join(e for lista in condiciones_form.errors.values() for e in lista)
        return None, [f"Revisá las condiciones del proceso: {detalle}"]

    mail_cliente = request.POST.get("mail_cliente", "").strip()
    if mail_cliente:
        try:
            validate_email(mail_cliente)
        except ValidationError:
            return None, ["El mail del cliente no es válido."]

    cliente = None
    if cliente_id and cliente_id.isdigit():
        cliente = Cliente.objects.filter(pk=cliente_id).first()
    elif nombre_nuevo:
        # Razón social y CUIT son opcionales acá: si no se cargan, el cliente los
        # completa (obligatorios) en el paso 1 del wizard.
        try:
            cuits_nuevo = normalizar_cuits(cuits_nuevo) if cuits_nuevo else ""
        except ValidationError as error:
            errores.append(error.messages[0])
        else:
            cliente = Cliente.objects.create(
                nombre=nombre_nuevo, razon_social=razon_social_nueva, cuits=cuits_nuevo,
            )
    if not cliente:
        return None, errores or ["Elegí un cliente existente o completá el nombre de la empresa."]

    if not cliente.usuario:
        _entregar_acceso(request, cliente, request.POST.get("username", "").strip(), mail_cliente)

    implementacion = Implementacion(
        cliente=cliente, creado_por=request.user, implementador_asignado=_implementador_elegido(request),
        mail_contacto=mail_cliente,  # el paso 1 del cliente ya lo trae cargado
        modulos_editables_por_cliente=bool(request.POST.get("modulos_editables")),
    )
    condiciones_form.aplicar(implementacion)
    implementacion.save()
    onboarding_services.guardar_modulos(
        implementacion, Modulo.objects.all(), modulo_ids, editado_por=request.user.get_username(),
    )
    return implementacion, []


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
            "estados_choices": Implementacion.VISUAL_LABELS.items(),
            "filtros_aplicados": request.GET,
            "sort_links": _sort_links(request),
        },
    )


@staff_member_required(login_url="login")
def cliente_detalle(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)

    if request.method == "POST" and request.POST.get("accion") == "regenerar_acceso":
        mail = _mail_valido(request)
        if mail is not None:
            _entregar_acceso(request, cliente, request.POST.get("username", "").strip(), mail)
        return redirect("dashboard:cliente_detalle", pk=pk)

    if request.method == "POST" and request.POST.get("accion") == "enviar_invitacion":
        _invitar_desde_panel(request, cliente)
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
        modulo_ids = {int(v) for v in request.POST.getlist("modulos") if v.isdigit()}
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

    if accion == "actualizar_condiciones":
        form = CondicionesForm(request.POST, implementacion=implementacion)
        if form.is_valid():
            onboarding_services.guardar_condiciones(implementacion, form, editado_por)
            messages.success(request, "Condiciones del proceso actualizadas.")
            return redirect("dashboard:implementacion_detalle", pk=pk)
        return {"condiciones_form": form}

    if accion == "reasignar":
        elegido = request.POST.get("implementador_id", "")
        nuevo = cuentas.asignables().filter(pk=elegido).first() if elegido.isdigit() else None
        if nuevo:
            implementacion.implementador_asignado = nuevo
            implementacion.save(update_fields=["implementador_asignado"])
            messages.success(request, f"Implementación asignada a {nuevo.get_full_name() or nuevo.username}.")
        return redirect("dashboard:implementacion_detalle", pk=pk)

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
        try:
            notificar_cliente_implementacion_cumplida(implementacion, request=request)
        except Exception:
            logger.exception("No se pudo avisar al cliente que la implementación %s está lista", pk)
            messages.warning(request, "Quedó cumplida, pero no se pudo avisarle al cliente por mail.")
        return redirect("dashboard:implementacion_detalle", pk=pk)

    if accion == "atender_revision":
        implementacion.marcar_revision_atendida()
        return redirect("dashboard:implementacion_detalle", pk=pk)

    if accion == "actualizar_fecha_productivo":
        # El equipo puede poner cualquier fecha (sin el mínimo que se le exige al cliente).
        onboarding_services.guardar_fecha_implementacion(
            implementacion, parse_date(request.POST.get("fecha_salida_productivo", "")), editado_por,
        )
        return redirect("dashboard:implementacion_detalle", pk=pk)

    if accion == "regenerar_acceso":
        mail = _mail_valido(request)
        if mail is not None:
            _entregar_acceso(request, implementacion.cliente, request.POST.get("username", "").strip(), mail)
        return redirect("dashboard:implementacion_detalle", pk=pk)

    if accion == "enviar_invitacion":
        _invitar_desde_panel(request, implementacion.cliente, implementacion)
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
        "asignables": cuentas.asignables(),
        "condiciones_form": formularios_con_error.get("condiciones_form")
        or CondicionesForm(implementacion=implementacion),
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
