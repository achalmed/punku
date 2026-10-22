"""tests/test_entradas.py — ficha automática de los documentos RECIBIDOS
(servicios/entradas.py): número STD, fecha, asunto, referencia, documento de origen,
clase, atención, remitente, plazo, duplicados y la cita desde un oficio propio.

Pruebas puras (sin base de datos). Los textos son INVENTADOS: ninguna institución,
persona ni número corresponde a un documento real.
Uso: cd backend && .venv/bin/python -m pytest -q tests/test_entradas.py
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:y@127.0.0.1/z")
os.environ.setdefault("JWT_SECRET", "prueba")

from punku import entradas as e  # noqa: E402
from punku.entradas import nombre_archivo as nombre_entrada  # noqa: E402

OFICIO = """MUNICIPALIDAD DISTRITAL DE VILLA EJEMPLO
"Año de la Prueba Unitaria"

Villa Ejemplo, 3 de octubre de 2026

OFICIO N° 0456-2026-MDVE/A

Señor:
CONGRESISTA DE LA REPÚBLICA
Presente.-

ASUNTO     : Solicito apoyo para la gestión del proyecto de agua
             potable del centro poblado Los Pinos
REFERENCIA : Oficio N° 0031-2026-2027-XYZ-CD/CRP

De mi consideración:
Tengo el agrado de dirigirme a usted para saludarlo y, a la vez, solicitarle que
interponga sus buenos oficios ante el Ministerio de Prueba para el financiamiento.

Atentamente,
Rosa Elena Quispe Huamaní
Alcaldesa
"""

CARTA_SINDICATO = """SINDICATO UNIFICADO DE TRABAJADORES DE PRUEBA
Registro STD N° 2437652

Lima, 29 de setiembre del 2026

CARTA N° 012-2026-SUTP

Asunto: Pedimos no otorgar facultades legislativas en materia laboral
Ref.: Proyecto de Ley 1234/2026-PE

Por medio de la presente, solicitamos su voto en contra.
"""

INVITACION = """COLEGIO DE INGENIEROS DE EJEMPLO
Lima, 01/10/2026
INVITACIÓN
Tenemos el agrado de invitarle a la ceremonia de aniversario institucional.
"""


def test_std_del_nombre_y_del_texto():
    assert e.extraer_std("2437652-OFICIO-0456-2026.pdf") == "2437652"
    assert e.extraer_std("2437652_carta sindicato (1).pdf") == "2437652"
    assert e.extraer_std("2437652.pdf") == "2437652"
    # Sin prefijo en el nombre: el que el texto rotula como registro STD.
    assert e.extraer_std("carta.pdf", CARTA_SINDICATO) == "2437652"
    assert e.extraer_std("x.pdf", "Expediente STD: 1234567 del día") == "1234567"
    assert e.extraer_std("x.pdf", "Hoja de trámite N.° 7654321") == "7654321"
    # Un número suelto que no está rotulado no es el STD.
    assert e.extraer_std("informe-2026.pdf", "Ley N° 27795 del 2002") == ""
    assert e.extraer_std("OFICIO-0456.pdf", OFICIO) == ""


def test_nombre_limpio_quita_descargas_repetidas():
    assert e.nombre_limpio("2437652-OFICIO (1).pdf") == "2437652-OFICIO.pdf"
    assert e.nombre_limpio("carta (12).pdf") == "carta.pdf"
    assert e.nombre_limpio("carta.pdf") == "carta.pdf"


def test_fecha_escrita_antes_que_numerica():
    assert e.extraer_fecha(OFICIO) == "2026-10-03"
    assert e.extraer_fecha(CARTA_SINDICATO) == "2026-09-29"   # «setiembre», «del»
    assert e.extraer_fecha(INVITACION) == "2026-10-01"        # numérica dd/mm/aaaa
    assert e.extraer_fecha("Recibido: 2026-08-15") == "2026-08-15"
    assert e.extraer_fecha("31 de febrero de 2026") == ""     # fecha imposible
    assert e.extraer_fecha("sin fecha") == ""


def test_asunto_y_referencia_con_continuacion():
    assert e.extraer_asunto(OFICIO) == (
        "Solicito apoyo para la gestión del proyecto de agua potable del centro poblado Los Pinos"
    )
    assert e.extraer_referencia(OFICIO) == "Oficio N° 0031-2026-2027-XYZ-CD/CRP"
    assert e.extraer_asunto(CARTA_SINDICATO) == "Pedimos no otorgar facultades legislativas en materia laboral"
    assert e.extraer_referencia(CARTA_SINDICATO) == "Proyecto de Ley 1234/2026-PE"
    assert e.extraer_asunto(INVITACION) == ""


def test_documento_de_origen_y_clase():
    assert e.extraer_documento(OFICIO) == ("Oficio N° 0456-2026-MDVE/A", "oficio")
    assert e.extraer_documento(CARTA_SINDICATO) == ("Carta N° 012-2026-SUTP", "carta")
    assert e.extraer_documento(INVITACION) == ("", "")
    assert e.clase_de(INVITACION) == "invitacion"
    assert e.clase_de("CITACIÓN a la tercera sesión ordinaria") == "citacion"
    assert e.clase_de(OFICIO, "oficio") == "oficio"


def test_atencion_sugerida():
    assert e.atencion_sugerida(INVITACION, "invitacion") == "agendar"
    assert e.atencion_sugerida(OFICIO, "oficio") == "interceder"
    assert e.atencion_sugerida(CARTA_SINDICATO, "carta") == "responder"
    assert e.atencion_sugerida("Se solicita emitir opinión sobre el PL 1234", "oficio") == "emitir_opinion"
    assert e.atencion_sugerida("En atención a su oficio, remitimos la información.", "oficio", True) == "conocimiento"
    assert e.atencion_sugerida("Remitimos el informe anual.", "informe") == "conocimiento"


def test_remitente_cruzado_con_el_directorio():
    insts = [(1, "Municipalidad Distrital de Villa Ejemplo", "MDVE"), (2, "Ministerio de Prueba", "MINPRU")]
    personas = [(7, "Rosa Elena Quispe Huamaní", 1, "Alcaldesa"), (8, "Ana Pérez", None, "")]
    r = e.cruzar_remitente(OFICIO, insts, personas)
    assert (r.persona_id, r.institucion_id, r.texto, r.cargo) == (7, 1, "Rosa Elena Quispe Huamaní", "Alcaldesa")
    # Sin la persona: la institución del membrete (no la del cuerpo, que es el Ministerio).
    r = e.cruzar_remitente(OFICIO, insts, [])
    assert (r.persona_id, r.institucion_id) == (None, 1)
    # Fuera del directorio: la línea del membrete que nombra una organización.
    r = e.cruzar_remitente(CARTA_SINDICATO, insts, personas)
    assert (r.persona_id, r.institucion_id) == (None, None)
    assert r.texto == "SINDICATO UNIFICADO DE TRABAJADORES DE PRUEBA"


def test_duplicados_por_huella_y_por_std():
    existentes = [(1, "a" * 64, "2437652"), (2, "b" * 64, "")]
    assert e.duplicado("a" * 64, "", existentes) == {"id": 1, "motivo": "mismo archivo (huella idéntica)"}
    assert e.duplicado("c" * 64, "2437652", existentes)["id"] == 1
    assert "STD" in e.duplicado("c" * 64, "2437652", existentes)["motivo"]
    assert e.duplicado("c" * 64, "", existentes) is None
    assert e.duplicado("c" * 64, "9999999", existentes) is None


def test_cita_desde_la_referencia_de_un_oficio_propio():
    assert e.cita_entrada("Carta N° 012-2026-SUTP (Reg. STD N° 2437652)", "2437652")
    assert e.cita_entrada("Registro 2437652", "2437652")
    assert not e.cita_entrada("Registro 24376521", "2437652")    # dentro de otro número, no
    assert e.cita_entrada("a) Oficio N.° 0456-2026-MDVE/A", "", "Oficio N° 0456-2026-MDVE/A")
    assert not e.cita_entrada("Oficio N° 0457-2026-MDVE/A", "", "Oficio N° 0456-2026-MDVE/A")
    assert not e.cita_entrada("", "2437652")


def test_vencida_y_por_vencer():
    assert e.vencida("2026-10-01", "nueva", "2026-10-06")
    assert not e.vencida("2026-10-01", "respondida", "2026-10-06")
    assert not e.vencida("", "nueva", "2026-10-06")
    assert e.por_vencer("2026-10-07", "en_atencion", "2026-10-06")
    assert not e.por_vencer("2026-10-20", "en_atencion", "2026-10-06")


def test_nombre_del_archivo_de_la_entrada():
    n = nombre_entrada("2437652", "2026-10-03", "Sindicato Unificado", "Pedimos no otorgar facultades")
    assert n == "ENT-2437652-2026-10-03_Sindicato-Unificado_Pedimos-no-otorgar-facultades.pdf"
    assert nombre_entrada("", "", "", "").startswith("ENT-SN")
    assert len(nombre_entrada("1", "2026-10-03", "x" * 200, "y " * 200)) <= 100


# --- el resumen del grupo (prompt de recepción) ---------------------------------------------
# Formatos del repo `prompts` (skills/documentos-administrativos/references/recepcion-comunicado-y-agenda.md).

COMUNICADO = """🗂️ ENRUTAMIENTO: 📋 COMUNICADO → grupo de documentos externos. (Origen: 🟧 EXTERNO)
(Línea de uso interno. No copiar al grupo.)

📌 NUEVO DOCUMENTO RECIBIDO

📄 OFICIO N.° 0234-2026-MDVE/A
🏛️ Remitente: Municipalidad Distrital de Villa Ejemplo — Alcalde, Juan Prueba Ficticio
📅 Fecha del documento: 12/08/2026
📥 Recibido: 14/08/2026 (Correo institucional)
🔖 Registro STD: N.° 0004521
👤 Dirigido a: Despacho Congresal [nombre]

📝 ASUNTO:
"Solicito interceder ante el MEF para el proyecto
de agua potable de Los Pinos"

🔍 CONTENIDO:
- Proyecto CUI N.° 1234567 por S/ 1 000 000.
- Gestiones previas ante el MEF sin respuesta.

📚 Información solicitada:
- Estado del expediente.

✅ ACCIÓN REQUERIDA: Gestionar ante el MEF la priorización del proyecto.
⏳ PLAZO: 22/08/2026 (8 días)
🚦 PRIORIDAD: 🟡 MEDIA"""

AGENDA = """🗓 AGENDA — NUEVA ACTIVIDAD

📌 Décima Sesión Ordinaria de la Comisión de Educación
🏛 Convoca: Comisión de Educación del Congreso — Presidencia
📅 Fecha: Jueves 03/09/2026
🕒 Hora: 6:30 p. m.
📍 Lugar: Sala Grau — Palacio Legislativo
💻 Modalidad: Virtual (Teams)
👤 Participa: Congresista [nombre]

📝 ASUNTO:
"Citación a la Décima Sesión Ordinaria de la Comisión de Educación"

🔍 DETALLE:
- Agenda: predictamen sobre infraestructura educativa rural.

✅ CONFIRMACIÓN: Requerida hasta 02/09/2026
📎 ACCIÓN PREVIA: Designar por escrito al suplente.
📄 Documento: OFICIO N.° 1120-2026-CR/CEA
🚦 PRIORIDAD: 🔴 ALTA"""


def test_resumen_comunicado_llena_la_ficha():
    r = e.leer_resumen(COMUNICADO)
    f = r["ficha"]
    assert r["tipo"] == "comunicado" and r["evento"] is None
    assert f["documento"] == "OFICIO N.° 0234-2026-MDVE/A"
    assert f["remitente"] == "Municipalidad Distrital de Villa Ejemplo"
    assert f["remitente_cargo"] == "Alcalde, Juan Prueba Ficticio"
    assert f["asunto"] == "Solicito interceder ante el MEF para el proyecto de agua potable de Los Pinos"
    assert (f["fecha_documento"], f["fecha_recepcion"], f["plazo"]) == ("2026-08-12", "2026-08-14", "2026-08-22")
    assert f["via"] == "correo" and f["std_numero"] == "4521"
    assert f["atencion"] == "interceder" and f["clase"] == "oficio"
    assert "- Proyecto CUI N.° 1234567 por S/ 1 000 000." in f["resumen"]
    assert "Información solicitada: Estado del expediente." in f["resumen"]
    assert "Acción requerida: Gestionar ante el MEF" in f["resumen"]


def test_resumen_agenda_propone_el_evento():
    r = e.leer_resumen(AGENDA)
    f, ev = r["ficha"], r["evento"]
    assert r["tipo"] == "agenda"
    assert (f["clase"], f["atencion"], f["plazo"]) == ("citacion", "agendar", "2026-09-02")
    assert f["documento"] == "OFICIO N.° 1120-2026-CR/CEA"
    assert ev["titulo"] == "Décima Sesión Ordinaria de la Comisión de Educación"
    assert (ev["inicio"], ev["todo_el_dia"], ev["tipo"], ev["modalidad"]) == ("2026-09-03T18:30:00", False, "comision", "virtual")
    assert ev["lugar"] == "Sala Grau — Palacio Legislativo"
    assert "Acción previa: Designar por escrito al suplente." in ev["descripcion"]


def test_resumen_no_indica_y_sin_hora():
    texto = AGENDA.replace("6:30 p. m.", "NO INDICA").replace("🔖", "")
    r = e.leer_resumen(texto)
    assert r["evento"]["todo_el_dia"] and r["evento"]["inicio"] == "2026-09-03T00:00:00"
    sin_fecha = e.leer_resumen(AGENDA.replace("Jueves 03/09/2026", "NO INDICA"))
    assert sin_fecha["evento"] is None and sin_fecha["avisos"]
    c = e.leer_resumen(COMUNICADO.replace("N.° 0004521", "NO INDICA").replace(
        "Gestionar ante el MEF la priorización del proyecto.", "Ninguna — solo conocimiento."))
    assert "std_numero" not in c["ficha"] and c["ficha"]["atencion"] == "conocimiento"


def test_resumen_que_no_es_del_formato():
    r = e.leer_resumen("Hola, les comparto el oficio que llegó hoy.")
    assert r["tipo"] == "" and r["ficha"] == {} and r["avisos"]


def test_hora_y_registro_std():
    assert e._hora("15:00 h") == "15:00" and e._hora("9:00 a. m.") == "09:00" and e._hora("12:00 p. m.") == "12:00"
    assert e._registro_std("N.° 002420835") == "2420835"
    assert e._registro_std("Proposición Legislativa 00002-2026-CR") == ""
    assert e._registro_std("OF5FIL4-92862") == ""


# --- Word e imágenes a PDF; unión de partes (si las herramientas están instaladas) ------------

import shutil  # noqa: E402

import pytest  # noqa: E402


def test_imagen_a_pdf_y_union(tmp_path):
    if not shutil.which("pdfunite"):
        pytest.skip("sin poppler-utils")
    from PIL import Image

    for i, color in enumerate(("white", "gray")):
        Image.new("RGB", (60, 80), color).save(tmp_path / f"foto{i}.png")
    pdfs = [e.convertir_a_pdf(tmp_path / f"foto{i}.png", tmp_path) for i in range(2)]
    assert all(p.suffix == ".pdf" and e.es_pdf(p.read_bytes()[:8]) for p in pdfs)
    unido = e.unir_pdfs(pdfs, tmp_path / "unido.pdf")
    from tiqsi.pdf import contar_paginas

    assert contar_paginas(unido) == 2


def test_lo_que_no_se_convierte(tmp_path):
    (tmp_path / "hoja.xlsx").write_bytes(b"x")
    with pytest.raises(e.ErrorConversion):
        e.convertir_a_pdf(tmp_path / "hoja.xlsx", tmp_path)
    assert e.convertir_a_pdf(tmp_path / "ya.pdf", tmp_path) == tmp_path / "ya.pdf"


def test_categoria_por_reglas_2026_10_18():
    # Qué es para el despacho: lo que no se reconoce es «comunicacion», nunca una categoría forzada.
    assert e.categoria_de("Tenemos el agrado de invitarle a la sesión", "invitacion") == "invitacion"
    assert e.categoria_de("En atención a su Oficio N.° 0012-2026 le informamos…") == "respuesta"
    assert e.categoria_de("Cualquier texto", responde_a_propio=True) == "respuesta"
    assert e.categoria_de("Se adjunta el informe técnico solicitado", "informe") == "anexo"
    assert e.categoria_de("En seguimiento al expediente 004521 reiteramos el pedido") == "seguimiento"
    assert e.categoria_de("texto", expediente="EXP-2026-0045") == "seguimiento"
    assert e.categoria_de("La Federación de Transportistas expresa su pronunciamiento sobre el proyecto") == "pronunciamiento"
    assert e.categoria_de("Solicito una reunión con el despacho") == "comunicacion"
    assert e.categoria_de("") == "comunicacion"
    assert set(e.CATEGORIAS) == {"comunicacion", "respuesta", "invitacion", "seguimiento", "pronunciamiento", "anexo"}


def test_referencia_citada_reconoce_el_numero_completo():
    assert e.referencia_citada("Oficio N.° 0123-2026-DESP/XY") == {"serie": "OF", "numero": 123, "anio": 2026}
    assert e.referencia_citada("Su Oficio Múltiple Nº 045-2026-ABC") == {"serie": "OM", "numero": 45, "anio": 2026}
    assert e.referencia_citada("OF-0012") == {"serie": "OF", "numero": 12, "anio": None}
    assert e.referencia_citada("Memorando N° 7-2026") == {"serie": "MEM", "numero": 7, "anio": 2026}
    assert e.referencia_citada("Carta s/n") is None
    assert e.referencia_citada("") is None
