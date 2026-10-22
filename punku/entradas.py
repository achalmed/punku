"""BANDEJA DE ENTRADA (2026-10-06): documentos RECIBIDOS (modelos.Entrada).

La brecha que cierra: lo que llega al despacho —cartas de gremios, pedidos de
municipios, invitaciones, citaciones, respuestas de entidades— quedaba sin registro,
sin responsable y sin plazo; el equipo pegaba a mano «fichas» (remitente, fecha, n.º
STD, asunto) en el chat. Aquí esa ficha sale sola del PDF y queda como un registro con
estado.

Tres partes:

1. FICHA AUTOMÁTICA (puras, probadas en tests/test_entradas.py): del nombre del
   archivo y del texto del PDF se leen, por reglas deterministas, el número de
   registro STD, la fecha, el documento de origen («Oficio N° …»), el asunto, la
   referencia, la clase (oficio, carta, invitación…), el tipo de atención que pide y
   el remitente (cruzado con el directorio). Sin modelos de IA ni dependencias nuevas:
   el texto lo da `pdftotext` (poppler, el mismo del conteo de folios).
2. DUPLICADOS: por huella (SHA-256 del PDF) y por número STD. Avisa y no duplica.
3. CONCILIACIÓN con los documentos propios: un oficio que cita en su Referencia el
   número STD (o el número del documento de origen) de una entrada queda vinculado a
   ella (`relaciones`: `doc:N` → `entrada:M`, tipo `responde`); cuando ese oficio se
   firma o se envía, la entrada pasa a «respondida». Además, el aviso de plazo vencido.
4. EL RESUMEN DEL GRUPO (puras): el mensaje que el equipo escribe con el prompt de
   recepción se pega en la ficha y la llena; si es AGENDA, propone el evento.
5. WORD E IMÁGENES A PDF y UNIÓN de las partes de un mismo envío en un solo PDF.
"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("qillqa.entradas")

ESTADOS = ("nueva", "en_atencion", "respondida", "archivada")
ESTADOS_ABIERTOS = ("nueva", "en_atencion")
ATENCIONES = ("responder", "agendar", "emitir_opinion", "interceder", "conocimiento")
CLASES = ("oficio", "carta", "solicitud", "invitacion", "citacion", "informe", "otro")
# Qué es para el despacho (2026-10-18, Edison: «distinguir comunicaciones nuevas, respuestas a oficios previos,
# invitaciones, seguimiento de expedientes, respuestas de instituciones o gremios, anexos e informes»).
CATEGORIAS = ("comunicacion", "respuesta", "invitacion", "seguimiento", "pronunciamiento", "anexo")
# Las series propias y cómo las nombra un documento ajeno en su referencia («Oficio N.° 0123-2026-…»).
SERIES_PROPIAS = {
    "oficio multiple": "OM", "oficio múltiple": "OM", "oficio": "OF", "memorando": "MEM", "memorándum": "MEM",
    "carta": "CARTA", "informe": "INF", "solicitud": "SOL", "acta": "ACT",
    "of": "OF", "om": "OM", "mem": "MEM", "car": "CARTA", "inf": "INF", "sol": "SOL", "act": "ACT",
}
# `mesa_virtual`: lo presentado por la página pública de la mesa de partes virtual (2026-10-12, servicios/mesa_virtual.py).
VIAS = ("std", "correo", "mesa_partes", "mano", "otro", "mesa_virtual")

ETIQUETA_ESTADO = {"nueva": "Nueva", "en_atencion": "En atención", "respondida": "Respondida", "archivada": "Archivada"}
ETIQUETA_ATENCION = {
    "responder": "Responder", "agendar": "Agendar", "emitir_opinion": "Emitir opinión",
    "interceder": "Interceder", "conocimiento": "Para conocimiento",
}

# Estados del oficio propio con los que la entrada ya se da por respondida.
ESTADOS_DOC_RESPONDE = {"FIRMADO", "ENVIADO", "OBSERVADO_ENVIADO"}

MAX_PDF = 40 * 1024 * 1024  # 40 MB por archivo (un oficio con anexos rara vez pasa de 10)
DIAS_POR_VENCER = 2


# --- texto comparable -------------------------------------------------------------------


def normalizar(texto: str) -> str:
    """minúsculas, sin tildes ni signos, espacios simples."""
    t = unicodedata.normalize("NFKD", (texto or "").replace("º", "°")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def _espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto or "").strip()


# --- 1. ficha automática (puras) --------------------------------------------------------

# «2437652-OFICIO-…pdf», «2437652_carta.pdf», «2437652 Oficio.pdf»: 6 a 8 cifras al principio.
_RE_STD_NOMBRE = re.compile(r"^\s*(\d{6,8})(?=[\s_\-.(]|$)")
# «Registro STD N° 2437652», «N° de registro: 2437652», «Expediente STD 2437652», «STD: 2437652».
_RE_STD_TEXTO = re.compile(
    r"(?:\bS\.?\s?T\.?\s?D\.?\b|\bregistro\b|\breg\.|\bexpediente\b|\bexp\.|\bhoja\s+de\s+tr[aá]mite\b|\bH\.?\s?T\.?\b)"
    r"[^\d\n]{0,25}?(\d{6,8})\b",
    re.I,
)
_RE_COPIA = re.compile(r"\s*\(\d{1,3}\)\s*$")


def nombre_limpio(nombre: str) -> str:
    """El nombre del archivo sin el sufijo de descarga repetida: «x (1).pdf» → «x.pdf»."""
    p = Path(nombre or "")
    return f"{_RE_COPIA.sub('', p.stem).strip()}{p.suffix}"


def extraer_std(nombre: str, texto: str = "") -> str:
    """Número de registro STD: primero el prefijo del nombre (así lo descarga el STD);
    si no, el que el texto rotula como registro, expediente o STD."""
    m = _RE_STD_NOMBRE.match(Path(nombre_limpio(nombre)).stem)
    if m:
        return m.group(1)
    m = _RE_STD_TEXTO.search(texto or "")
    return m.group(1) if m else ""


MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "setiembre": 9, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}
_RE_FECHA_LARGA = re.compile(
    r"\b(\d{1,2})\s*(?:de\s+)?(" + "|".join(MESES) + r")\s+(?:de[l]?\s+)?(\d{4})\b", re.I
)
_RE_FECHA_CORTA = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b")
_RE_FECHA_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _fecha_valida(a: int, m: int, d: int) -> str:
    try:
        f = date(a, m, d)
    except ValueError:
        return ""
    return f.isoformat() if 2000 <= a <= 2100 else ""


def extraer_fecha(texto: str) -> str:
    """Fecha del documento (AAAA-MM-DD): la escrita «3 de octubre de 2026» (la del
    encabezado, «Lima, 3 de octubre de 2026») antes que la numérica «03/10/2026», que
    suele ser un sello de recepción. Solo se mira el principio del documento."""
    cabeza = unicodedata.normalize("NFC", (texto or "")[:4000])
    for m in _RE_FECHA_LARGA.finditer(cabeza):
        f = _fecha_valida(int(m.group(3)), MESES[m.group(2).lower()], int(m.group(1)))
        if f:
            return f
    for m in _RE_FECHA_CORTA.finditer(cabeza):
        f = _fecha_valida(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if f:
            return f
    for m in _RE_FECHA_ISO.finditer(cabeza):
        f = _fecha_valida(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if f:
            return f
    return ""


# Rótulos que cortan un campo de varias líneas (el asunto acaba donde empieza la referencia).
_RE_ROTULO = re.compile(
    r"^\s*(asunto|referencia|ref\b|ref\.|se[nñ]or|se[nñ]ora|se[nñ]ores|de\s*:|para\s*:|fecha\s*:|anexo|adj|"
    r"presente|me\s+dirijo|tengo\s+el\s+agrado|es\s+grato|por\s+medio|mediante\s+el\s+presente|de\s+mi\s+consideraci)",
    re.I,
)


def _campo_rotulado(texto: str, rotulo: str, maximo: int = 600) -> str:
    """El valor de un rótulo «ASUNTO : …» y sus líneas de continuación (hasta una línea
    en blanco, otro rótulo o tres líneas)."""
    lineas = (texto or "").splitlines()
    # El rótulo puede no abrir la línea: pdftotext pega «Presente.- ASUNTO: …» en una sola
    # («Presente.ASUNTO: Solicito…»); se admite tras un signo de cierre (auditoría 2026-10-10, RC-01).
    patron = re.compile(rf"^(?:\s*|.*?[.\-–:;]\s*)(?:{rotulo})\s*[:.\-–]?\s*(.*)$", re.I)
    for i, linea in enumerate(lineas):
        m = patron.match(linea)
        if not m:
            continue
        partes = [m.group(1).strip()]
        for sig in lineas[i + 1:i + 4]:
            if not sig.strip() or _RE_ROTULO.match(sig):
                break
            partes.append(sig.strip())
        valor = _espacios(" ".join(p for p in partes if p)).strip(" :.-–")
        if valor:
            return valor[:maximo]
    return ""


def extraer_asunto(texto: str) -> str:
    return _campo_rotulado(texto, r"asunto")


def extraer_referencia(texto: str) -> str:
    return _campo_rotulado(texto, r"referencia|ref\.?", maximo=400)


_CLASES_DOC = (
    ("oficio", r"oficio(?:\s+m[uú]ltiple|\s+circular)?"),
    ("carta", r"carta(?:\s+notarial|\s+m[uú]ltiple)?"),
    ("informe", r"informe(?:\s+t[eé]cnico|\s+legal)?"),
    ("solicitud", r"solicitud"),
    ("invitacion", r"invitaci[oó]n"),
    ("citacion", r"citaci[oó]n"),
    ("otro", r"memorando(?:\s+m[uú]ltiple)?|memor[aá]ndum|resoluci[oó]n(?:\s+\w+)?|acuerdo\s+de\s+concejo|esquela"),
)
_RE_DOCUMENTO = re.compile(
    r"^\s*(" + "|".join(p for _, p in _CLASES_DOC) + r")\s*(?:N\s*[.°º]*\s*|Nro\.?\s*|n[uú]mero\s*)?[:\s]*"
    r"(\d[\w\-./° ]{0,70})",
    re.I,
)


def extraer_documento(texto: str) -> tuple[str, str]:
    """(«Oficio N° 0456-2026-UGEL-H/D», «oficio»): la primera línea del encabezado que
    nombra un tipo documental con su número. ('', '') si no hay."""
    for linea in (texto or "").splitlines()[:40]:
        m = _RE_DOCUMENTO.match(linea)
        if not m:
            continue
        tipo = _espacios(m.group(1))
        numero = _espacios(m.group(2)).rstrip(" .-")
        clase = next((c for c, p in _CLASES_DOC if re.fullmatch(p, tipo, re.I)), "otro")
        return f"{tipo[:1].upper()}{tipo[1:].lower()} N° {numero}"[:300], clase
    return "", ""


def clase_de(texto: str, documento_clase: str = "") -> str:
    """oficio | carta | solicitud | invitacion | citacion | informe | otro."""
    n = normalizar((texto or "")[:3000])
    if re.search(r"\b(citacion|cita a (la )?sesion|convoca a (la )?sesion)\b", n):
        return "citacion"
    if re.search(r"\b(invitacion|invitarle|invitarlo|invitarla|invitamos|le invita|cordialmente invita)\b", n):
        return "invitacion"
    if documento_clase:
        return documento_clase
    if re.search(r"\bsolicito\b|\bsolicitud\b", n):
        return "solicitud"
    return "otro"


def categoria_de(texto: str, clase: str = "", responde_a_propio: bool = False, expediente: str = "", reunion: str = "") -> str:
    """comunicacion | respuesta | invitacion | seguimiento | pronunciamiento | anexo, solo por reglas (la
    ficha automática de un PDF). Lo que no se reconoce es «comunicacion», nunca una categoría forzada
    con menos señales: la IA del prompt 13 afina y, si duda, la persona confirma."""
    n = normalizar((texto or "")[:4000])
    if clase in ("invitacion", "citacion") or re.search(r"\b(invita|convoca|citacion|citar a)\w*", n):
        return "invitacion"
    if responde_a_propio or re.search(r"\b(en atencion a su oficio|en respuesta a su|en respuesta al oficio|dando respuesta a|absolviendo su|en relacion a su oficio|en relacion al oficio)\b", n):
        return "respuesta"
    if clase == "informe" or re.search(r"\b(se adjunta|adjunto|adjuntamos|anexo|anexos|informe tecnico|informe legal|remito el informe|remitimos el informe)\b", n) and re.search(r"\b(adjunt|anex|informe)\w*", n):
        return "anexo"
    if expediente or re.search(r"\b(expediente|en seguimiento|seguimiento al|estado del tramite|estado de la solicitud|continuando|en continuidad|reiteramos|reitero)\w*", n):
        return "seguimiento"
    if reunion or re.search(r"\b(pronunciamiento|posicion institucional|nos pronunciamos|manifestamos nuestr|rechazamos|respaldamos|expresamos nuestr|gremio|sindicato|federacion|colegio profesional|camara de comercio)\w*", n):
        return "pronunciamiento"
    return "comunicacion"


def referencia_citada(texto: str) -> dict | None:
    """La cita de un documento PROPIO dentro de una referencia ajena: «Oficio N.° 0123-2026-XXX» →
    {serie: 'OF', numero: 123, anio: 2026}; «OF-0123» → sin año. None si no hay número reconocible.
    Pura; la consulta a la base la hace quien llama."""
    t = normalizar(texto or "")
    # `normalizar` ya quitó puntos, guiones y «N.°»: queda «oficio n 0123 2026 desp xy».
    m = re.search(r"\b(oficio multiple|oficio|memorando|memorandum|carta|informe|solicitud|acta|of|om|mem|car|inf|sol|act)\b\s*(?:n\s+)?0*(\d{1,5})(?:\s+(?:de\s+)?((?:19|20)\d{2}))?\b", t)
    if not m:
        return None
    serie = SERIES_PROPIAS.get(m.group(1))
    if not serie:
        return None
    anio = int(m.group(3)) if m.group(3) else None
    return {"serie": serie, "numero": int(m.group(2)), "anio": anio}


def atencion_sugerida(texto: str, clase: str = "", responde_a_propio: bool = False) -> str:
    """Qué pide el documento, por reglas: una invitación o citación se AGENDA; quien
    pide opinión, OPINIÓN; quien pide gestionar ante otra entidad, INTERCEDER; la
    respuesta a un oficio propio es para CONOCIMIENTO; quien solicita algo, RESPONDER."""
    n = normalizar(texto or "")
    if clase in ("invitacion", "citacion"):
        return "agendar"
    if re.search(r"\b(opinion|pronunciamiento)\b", n) and re.search(r"\b(solicit|emit|requier|pid)\w*", n):
        return "emitir_opinion"
    if re.search(r"\b(interceda|interceder|intercesion|gestione ante|gestionar ante|su intervencion ante|interponga sus buenos oficios|buenos oficios)\b", n):
        return "interceder"
    if responde_a_propio:
        return "conocimiento"
    if re.search(r"\b(solicito|solicitamos|solicitarle|pedimos|requerimos|le pido|rogamos|exigimos|demandamos|se sirva)\b", n):
        return "responder"
    return "conocimiento"


def _dias_habiles(desde: date, dias: int) -> date:
    """`dias` hábiles después de `desde` (servicios/feriados.py: sábados, domingos, feriados y días no
    laborables del Perú)."""
    from punku import puertos

    return puertos.dias_habiles(desde, dias)   # «calendario.v1» (Punku P1a)


PLAZO_DIAS_HABILES = {"responder": 5, "emitir_opinion": 7, "interceder": 7, "agendar": 2}


def plazo_sugerido(atencion: str, recepcion: str) -> str:
    """Plazo de atención en días hábiles desde la recepción (vacío para lo que es de
    conocimiento). Es una propuesta: la secretaría lo corrige en la ficha."""
    dias = PLAZO_DIAS_HABILES.get(atencion)
    if not dias:
        return ""
    try:
        base = date.fromisoformat(recepcion)
    except ValueError:
        base = date.today()
    return _dias_habiles(base, dias).isoformat()


# Remitentes que no están en el directorio: la línea del membrete que nombra una organización.
_RE_ORGANIZACION = re.compile(
    r"\b(SINDICATO|FEDERACI[OÓ]N|CONFEDERACI[OÓ]N|ASOCIACI[OÓ]N|MUNICIPALIDAD|GOBIERNO\s+REGIONAL|UNIVERSIDAD|"
    r"COLEGIO|FRENTE|COMUNIDAD|DIRECCI[OÓ]N|UGEL|MINISTERIO|INSTITUTO|C[AÁ]MARA|CENTRAL|COMIT[EÉ]|RONDAS?|"
    r"COOPERATIVA|GREMIO|JUNTA|CONSEJO|ORGANIZACI[OÓ]N|PARROQUIA|RED\s+DE)\b",
    re.I,
)


@dataclass
class Remitente:
    texto: str = ""
    persona_id: int | None = None
    institucion_id: int | None = None
    cargo: str = ""
    motivo: str = ""


def _con_bordes(t: str) -> str:
    return f" {t} "


def cruzar_remitente(
    texto: str,
    instituciones: list[tuple[int, str, str]],
    personas: list[tuple[int, str, int | None, str]],
) -> Remitente:
    """Remitente del documento cruzado con el directorio. Se mira el MEMBRETE (primeras
    líneas) y la FIRMA (últimas): una persona del directorio cuyo nombre completo
    aparece allí (gana la de nombre más largo) y una institución cuyo nombre (o siglas
    de 4 letras o más) aparece en el membrete. Sin coincidencia, la línea del membrete
    que nombra una organización, como texto libre.

    `instituciones`: (id, nombre, siglas); `personas`: (id, nombre, institucion_id, cargo)."""
    lineas = [ln for ln in (texto or "").splitlines() if ln.strip()]
    cabeza = "\n".join(lineas[:25])
    firma = "\n".join(lineas[-25:])
    zona = _con_bordes(normalizar(cabeza + "\n" + firma))
    zona_cabeza = _con_bordes(normalizar(cabeza))
    r = Remitente()

    mejor_p: tuple[int, int, str, int | None, str] | None = None
    for pid, nombre, inst_id, cargo in personas:
        n = normalizar(nombre)
        if len(n.split()) < 3:
            continue  # «Juan Pérez» aparece en cualquier parte: hacen falta nombre y dos apellidos
        if _con_bordes(n) in zona and (mejor_p is None or len(n) > mejor_p[0]):
            mejor_p = (len(n), pid, nombre, inst_id, cargo)
    mejor_i: tuple[int, int, str] | None = None
    for iid, nombre, siglas in instituciones:
        n = normalizar(nombre)
        if len(n) >= 12 and len(n.split()) >= 2 and _con_bordes(n) in zona_cabeza:
            if mejor_i is None or len(n) > mejor_i[0]:
                mejor_i = (len(n), iid, nombre)
    if mejor_i is None:
        for iid, nombre, siglas in instituciones:
            s = normalizar(siglas)
            if len(s) >= 4 and " " not in s and _con_bordes(s) in zona_cabeza:
                if mejor_i is None or len(s) > mejor_i[0]:
                    mejor_i = (len(s), iid, nombre)

    if mejor_p is not None:
        _, r.persona_id, r.texto, inst_id, r.cargo = mejor_p
        r.institucion_id = mejor_i[1] if mejor_i else inst_id
        r.motivo = "persona del directorio en el membrete o la firma"
        return r
    if mejor_i is not None:
        r.institucion_id, r.texto = mejor_i[1], mejor_i[2]
        r.motivo = "institución del directorio en el membrete"
        return r
    for linea in lineas[:12]:
        if _RE_ORGANIZACION.search(linea) and not _RE_DOCUMENTO.match(linea) and len(linea.strip()) <= 160:
            r.texto = _espacios(linea).strip(" «»\"'")
            r.motivo = "membrete (no está en el directorio)"
            return r
    return r


def similitud(a: str, b: str) -> float:
    """Jaccard de palabras significativas (≥ 4 letras): 1 = mismo asunto."""
    pa = {p for p in normalizar(a).split() if len(p) >= 4}
    pb = {p for p in normalizar(b).split() if len(p) >= 4}
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / len(pa | pb)


def campana_sugerida(asunto: str, previas: list[tuple[str, str]], umbral: float = 0.5) -> str:
    """Si el asunto se parece a una entrada que ya está en una campaña (cartas iguales
    de varios gremios), esa campaña. `previas`: (asunto, campaña)."""
    mejor, valor = "", umbral
    for otro, campana in previas:
        if not campana:
            continue
        s = similitud(asunto, otro)
        if s >= valor:
            mejor, valor = campana, s
    return mejor


@dataclass
class Ficha:
    std_numero: str = ""
    documento: str = ""
    clase: str = "otro"
    fecha_documento: str = ""
    fecha_recepcion: str = ""
    asunto: str = ""
    referencia: str = ""
    resumen: str = ""
    atencion: str = "conocimiento"
    categoria: str = "comunicacion"
    plazo: str = ""
    remitente: str = ""
    remitente_cargo: str = ""
    remitente_persona_id: int | None = None
    remitente_institucion_id: int | None = None
    campana: str = ""
    sin_texto: bool = False
    avisos: list[str] = field(default_factory=list)

    def como_dict(self) -> dict:
        return dict(self.__dict__)


def resumen_breve(texto: str, asunto: str = "", maximo: int = 420) -> str:
    """Las primeras frases del CUERPO (después del saludo), para la ficha. Determinista:
    no resume, recorta. Sin cuerpo reconocible, vacío."""
    lineas = (texto or "").splitlines()
    inicio = None
    for i, linea in enumerate(lineas):
        if re.match(r"^\s*(tengo el agrado|es grato|me dirijo|nos dirigimos|por medio de|mediante el presente|"
                    r"reciba|con el debido respeto|de mi consideraci|de nuestra consideraci)", linea, re.I):
            inicio = i
            break
    if inicio is None:
        return ""
    cuerpo = _espacios(" ".join(lineas[inicio:inicio + 12]))
    if len(cuerpo) <= maximo:
        return cuerpo
    corte = cuerpo[:maximo].rsplit(" ", 1)[0]
    return corte + "…"


def construir_ficha(
    nombre: str,
    texto: str,
    *,
    hoy: str,
    instituciones: list[tuple[int, str, str]] = (),
    personas: list[tuple[int, str, int | None, str]] = (),
    siglas_propias: str = "",
    previas: list[tuple[str, str]] = (),
) -> Ficha:
    """La ficha completa de un PDF recibido, solo por reglas. `hoy` (AAAA-MM-DD) es la
    fecha de recepción por omisión; `siglas_propias` (las de la entidad, del .env) dice si
    la referencia cita un documento propio, y entonces es una respuesta."""
    f = Ficha(fecha_recepcion=hoy)
    f.sin_texto = len((texto or "").strip()) < 40
    f.std_numero = extraer_std(nombre, texto)
    f.documento, clase_doc = extraer_documento(texto)
    f.clase = clase_de(texto, clase_doc)
    f.fecha_documento = extraer_fecha(texto)
    f.asunto = extraer_asunto(texto)
    f.referencia = extraer_referencia(texto)
    f.resumen = resumen_breve(texto, f.asunto)
    propias = normalizar(siglas_propias)
    responde = bool(propias and f.referencia and propias in normalizar(f.referencia))
    f.atencion = atencion_sugerida(texto, f.clase, responde)
    f.categoria = categoria_de(texto, f.clase, responde)
    f.plazo = plazo_sugerido(f.atencion, f.fecha_recepcion)
    r = cruzar_remitente(texto, list(instituciones), list(personas))
    f.remitente, f.remitente_cargo = r.texto, r.cargo
    f.remitente_persona_id, f.remitente_institucion_id = r.persona_id, r.institucion_id
    if not f.asunto:
        # Sin rótulo «Asunto», el nombre del archivo sin el número STD suele decirlo.
        tallo = Path(nombre_limpio(nombre)).stem
        tallo = _RE_STD_NOMBRE.sub("", tallo).strip(" -_")
        f.asunto = _espacios(re.sub(r"[_\-]+", " ", tallo))[:300]
        if f.asunto:
            f.avisos.append("El asunto sale del nombre del archivo: revíselo.")
    f.campana = campana_sugerida(f.asunto, list(previas))
    if f.sin_texto:
        f.avisos.append("El PDF no tiene texto (es un escaneo): complete la ficha a mano.")
    if not f.std_numero:
        f.avisos.append("No se encontró el número de registro STD.")
    if responde:
        f.avisos.append("La referencia cita un documento de la entidad: parece una respuesta.")
    return f


# --- 2. duplicados (pura) ---------------------------------------------------------------


def duplicado(sha256: str, std: str, existentes: list[tuple[int, str, str]]) -> dict | None:
    """¿Ya está registrada? `existentes`: (id, sha256, std_numero). Por huella es el MISMO
    archivo; por número STD es el mismo trámite (otra descarga u otro escaneo)."""
    for eid, sha, n in existentes:
        if sha256 and sha == sha256:
            return {"id": eid, "motivo": "mismo archivo (huella idéntica)"}
    if std:
        for eid, sha, n in existentes:
            if n and n == std:
                return {"id": eid, "motivo": f"mismo número de registro STD ({std})"}
    return None


def huella(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as fh:
        for trozo in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(trozo)
    return h.hexdigest()


# --- texto del PDF y carpetas -----------------------------------------------------------


def texto_pdf(ruta: Path, paginas: int = 4) -> str:
    """Texto de las primeras páginas (pdftotext, de poppler). Vacío si no hay capa de
    texto o la herramienta falta: la ficha se completa a mano."""
    try:
        salida = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", "-l", str(paginas), str(ruta), "-"],
            capture_output=True, timeout=40,
        )
        return salida.stdout.decode("utf-8", "replace") if salida.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def es_pdf(cabecera: bytes) -> bool:
    return cabecera[:5] == b"%PDF-"


def raiz_entradas() -> Path:
    """Carpeta de la bandeja de entrada dentro del archivo documental: la del tipo
    `recibido` del registro de tipos (documentos/recibidos) y, dentro, `entradas/`."""
    from punku.config import CARPETA_RECIBIDOS, raiz

    return raiz() / CARPETA_RECIBIDOS / "entradas"


def carpeta_por_confirmar() -> Path:
    """Donde esperan los PDF analizados hasta que se confirma su ficha (se limpian
    solos a las 24 h)."""
    c = raiz_entradas() / ".por-confirmar"
    c.mkdir(parents=True, exist_ok=True)
    limite = time.time() - 24 * 3600
    for p in c.glob("*.pdf"):
        try:
            if p.stat().st_mtime < limite:
                p.unlink()
        except OSError:
            pass
    return c


_RE_TOKEN = re.compile(r"^[0-9a-f]{64}$")


def ruta_por_confirmar(token: str) -> Path | None:
    if not _RE_TOKEN.match(token or ""):
        return None
    ruta = raiz_entradas() / ".por-confirmar" / f"{token}.pdf"
    return ruta if ruta.is_file() else None


def ruta_de(archivo: str) -> Path | None:
    """Ruta absoluta del PDF de una entrada (guardada relativa a la raíz documental)."""
    from punku.config import raiz as raiz_documentos

    if not archivo:
        return None
    raiz = raiz_documentos().resolve()
    ruta = (raiz / archivo).resolve()
    if raiz not in ruta.parents:
        return None
    return ruta if ruta.is_file() else None


def nombre_archivo(std: str, fecha: str, remitente: str, asunto: str, ext: str = ".pdf") -> str:
    """Nombre del PDF de un documento RECIBIDO (bandeja de entrada, 2026-10-06):
    «ENT-2437652-2026-10-03_SUTE-Huanta_Delegacion-de-facultades.pdf». El número de
    registro STD va primero (es por lo que se busca y como lo descarga el STD); sin él,
    «SN». La descripción es el remitente y el asunto, recortados por palabras. Es de la Mesa de Partes (Punku P1c;
    antes `nombres.entrada` de Qillqa); el largo máximo y `sanear`, la convención común (tiqsi.nombres)."""
    from tiqsi.nombres import LIMITE, sanear

    numero = re.sub(r"\D", "", std or "") or "SN"
    cabeza = f"ENT-{numero}" + (f"-{fecha}" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha or "") else "")
    ext = ext if ext.startswith(".") else f".{ext}"
    disponible = LIMITE - len(cabeza) - len(ext) - 1
    quien = sanear(remitente, 30)
    que = sanear(asunto, max(disponible - len(quien) - 1, 0))
    cuerpo = "_".join(x for x in (quien, que) if x)[:disponible].strip("-_")
    return f"{cabeza}{'_' + cuerpo if cuerpo else ''}{ext}"


def archivar_pdf(origen: Path, nombre: str, recepcion: str) -> str:
    """Mueve el PDF confirmado a su carpeta del mes (`entradas/AAAA-MM/`) con su nombre
    de la convención (`nombre_archivo`) y devuelve la ruta RELATIVA a la raíz."""
    from tiqsi.nombres import unico_en

    from punku.config import raiz as raiz_documentos

    mes = recepcion[:7] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", recepcion or "") else date.today().isoformat()[:7]
    carpeta = raiz_entradas() / mes
    carpeta.mkdir(parents=True, exist_ok=True)
    final = carpeta / unico_en(carpeta, nombre)
    shutil.move(str(origen), str(final))
    return str(final.relative_to(raiz_documentos()))


# --- 3. conciliación con los documentos propios -----------------------------------------


def clave_numero(texto: str) -> str:
    """«Oficio N° 0456-2026-UGEL-H» → «OFICIO0456-2026-UGEL-H» (como servicios/grafo.py)."""
    t = unicodedata.normalize("NFKC", (texto or "").replace("º", "°")).upper()
    t = re.sub(r"N\s*\.?\s*[°º]\s*", "", t)
    return re.sub(r"\s+", "", t)


def cita_entrada(referencia: str, std: str, documento: str = "") -> bool:
    """¿La referencia de un oficio propio cita esta entrada? Por su número STD (como
    número completo, no dentro de otro) o por el número de su documento de origen."""
    if not referencia:
        return False
    if std and re.search(rf"(?<!\d){re.escape(std)}(?!\d)", referencia):
        return True
    clave = clave_numero(documento)
    return bool(clave and re.search(r"\d", clave) and len(clave) >= 8 and clave in clave_numero(referencia))


def vencida(plazo: str, estado: str, hoy: str) -> bool:
    return bool(plazo) and estado in ESTADOS_ABIERTOS and plazo < hoy


def por_vencer(plazo: str, estado: str, hoy: str, dias: int = DIAS_POR_VENCER) -> bool:
    if not plazo or estado not in ESTADOS_ABIERTOS or plazo < hoy:
        return False
    try:
        return (date.fromisoformat(plazo) - date.fromisoformat(hoy)).days <= dias
    except ValueError:
        return False


def hoy_lima() -> str:
    from zoneinfo import ZoneInfo

    from punku.config import config

    try:
        return datetime.now(ZoneInfo(config.zona_horaria)).date().isoformat()
    except Exception:  # zona desconocida: la del servidor
        return date.today().isoformat()


def texto_cita(e) -> str:
    """Cómo se cita la entrada en la Referencia de un oficio: «Oficio N° … (Reg. STD N° …)»."""
    base = e.documento or (f"Documento de {e.remitente}" if e.remitente else "Documento recibido")
    return f"{base} (Reg. STD N° {e.std_numero})" if e.std_numero else base


def relacion_respuesta(entrada, doc_id: int, contexto: str, usuario_id: int | None) -> dict:
    """La relación `doc:N` → `entrada:M` (responde) que acompaña a `vincular`: la registra Qillqa, que es dueña del grafo
    (por «relaciones.v1» cuando la pide la Mesa de Partes, en su propia transacción cuando concilia un documento)."""
    return {"origen": f"doc:{int(doc_id)}", "destino": f"entrada:{entrada.id}", "tipo": "responde", "contexto": contexto,
            "fuente": "auto", "texto": texto_cita(entrada), "usuario_id": usuario_id}


async def vincular(sesion: AsyncSession, entrada, doc: dict, usuario_id: int | None, contexto: str) -> bool:
    """El efecto en la entrada de que el documento propio `doc` ({id, estado}) la responda: pasa a «en atención» y, si
    el oficio ya está firmado o enviado, a «respondida» (con su evento y su aviso, por la bandeja). Devuelve si cambió
    algo de la entrada. No hace commit ni registra la relación (`relacion_respuesta`)."""
    from punku import eventos as punku_eventos

    cambio = False
    if entrada.respuesta_documento_id is None:
        entrada.respuesta_documento_id = doc["id"]
        cambio = True
    if entrada.estado == "nueva":
        entrada.estado = "en_atencion"
        cambio = True
    if doc["estado"] in ESTADOS_DOC_RESPONDE and entrada.estado == "en_atencion":
        entrada.estado = "respondida"
        entrada.respondida_en = datetime.now(timezone.utc)
        cambio = True
        punku_eventos.emitir(sesion, "entrada.respondida", f"entrada:{entrada.id}",
                             {"asunto": entrada.asunto or entrada.documento or "", "responsable_id": entrada.responsable_id,
                              "documento": f"doc:{doc['id']}"}, usuario_id=usuario_id)
        punku_eventos.avisar(
            sesion, entrada.responsable_id or entrada.creado_por,
            f"Recibido respondido: «{(entrada.asunto or entrada.documento)[:120]}» (el oficio de respuesta pasó a {doc['estado'].lower()}).",
            tipo="entrada", destino=f"entrada:{entrada.id}", evitar=usuario_id,
        )
    return cambio


async def conciliar_documento(sesion: AsyncSession, doc: dict, usuario_id: int | None = None) -> dict:
    """Tras guardar o cambiar de estado un documento propio (`doc` = {id, estado, referencia}): lo vincula con las
    entradas que su Referencia cita y, si ya está firmado o enviado, da por respondidas las entradas que responde.
    → {tocadas, citadas (ids), relaciones (las de `relacion_respuesta`, para que Qillqa las registre y retire las
    automáticas por referencia que ya no cita)}. No hace commit."""
    from punku.modelos import Entrada

    referencia = str(doc.get("referencia") or "")
    citadas: list = []
    if referencia.strip():
        candidatas = (await sesion.execute(
            select(Entrada).where(Entrada.estado != "archivada", or_(Entrada.std_numero != "", Entrada.documento != ""))
        )).scalars().all()
        citadas = [e for e in candidatas if cita_entrada(referencia, e.std_numero, e.documento)]
    tocadas, relaciones = 0, []
    ids_citadas = {e.id for e in citadas}
    for e in citadas:
        relaciones.append(relacion_respuesta(e, doc["id"], "referencia", usuario_id))
        if await vincular(sesion, e, doc, usuario_id, "referencia"):
            tocadas += 1
    # Las que responde por «Responder» o por un vínculo manual: su estado sigue al oficio.
    if doc["estado"] in ESTADOS_DOC_RESPONDE:
        otras = (await sesion.execute(
            select(Entrada).where(Entrada.respuesta_documento_id == doc["id"], Entrada.estado == "en_atencion")
        )).scalars().all()
        for e in otras:
            if e.id not in ids_citadas:
                relaciones.append(relacion_respuesta(e, doc["id"], "responder", usuario_id))
                if await vincular(sesion, e, doc, usuario_id, "responder"):
                    tocadas += 1
    return {"tocadas": tocadas, "citadas": ids_citadas, "relaciones": relaciones}


async def conciliar_todo(sesion: AsyncSession) -> tuple[int, list[dict]]:
    """Pasada completa (al abrir la bandeja de recibidos): cubre lo que se guardó antes de que existiera la bandeja o
    por un camino que no concilia. Los documentos, por «documentos.v1». → (entradas que cambiaron, relaciones que
    registrar después del commit)."""
    from punku.modelos import Entrada
    from punku import puertos

    abiertas = (await sesion.execute(
        select(Entrada).where(Entrada.estado.in_(ESTADOS_ABIERTOS))
    )).scalars().all()
    if not abiertas:
        return 0, []
    docs = await puertos.referencias_de_documentos()
    por_id = {d["id"]: d for d in docs}
    tocadas, relaciones = 0, []
    for e in abiertas:
        for d in docs:
            ref = d["referencia"]
            if ref and cita_entrada(ref, e.std_numero, e.documento):
                relaciones.append(relacion_respuesta(e, d["id"], "referencia", None))
                if await vincular(sesion, e, d, None, "referencia"):
                    tocadas += 1
        d = por_id.get(e.respuesta_documento_id) if e.respuesta_documento_id else None
        if d is not None and d["estado"] in ESTADOS_DOC_RESPONDE and e.estado == "en_atencion":
            relaciones.append(relacion_respuesta(e, d["id"], "responder", None))
            if await vincular(sesion, e, d, None, "responder"):
                tocadas += 1
    return tocadas, relaciones


async def avisar_vencidas(sesion: AsyncSession, hoy: str | None = None) -> int:
    """Un aviso por entrada cuyo plazo venció sin respuesta, a su responsable (o a quien
    la registró). Devuelve cuántos avisos creó. No hace commit."""
    from punku.modelos import Entrada
    from punku import eventos as punku_eventos

    hoy = hoy or hoy_lima()
    filas = (await sesion.execute(
        select(Entrada).where(Entrada.estado.in_(ESTADOS_ABIERTOS), Entrada.plazo != "",
                              Entrada.plazo < hoy, Entrada.aviso_vencida_en.is_(None))
    )).scalars().all()
    for e in filas:
        punku_eventos.avisar(
            sesion, e.responsable_id or e.creado_por,
            f"Sin respuesta: venció el plazo ({e.plazo}) de «{(e.asunto or e.documento or 'documento recibido')[:120]}».",
            tipo="entrada", destino=f"entrada:{e.id}",
        )
        e.aviso_vencida_en = datetime.now(timezone.utc)
        punku_eventos.emitir(sesion, "entrada.vencida", f"entrada:{e.id}",
                             {"asunto": e.asunto or e.documento or "", "responsable_id": e.responsable_id, "plazo": e.plazo or ""},
                             clave=f"entrada:{e.id}:vencida:{e.plazo}")
    return len(filas)


# --- 4. el resumen del grupo (puras) ------------------------------------------------------
# El equipo resume cada documento con el prompt de recepción (repo `prompts`,
# skills/documentos-administrativos/references/recepcion-comunicado-y-agenda.md): un mensaje de
# formato fijo, COMUNICADO («📌 NUEVO DOCUMENTO RECIBIDO») o AGENDA («🗓️ AGENDA — NUEVA
# ACTIVIDAD»). Pegado en la ficha, llena sus campos; si es AGENDA, propone además el
# evento. Se lee por los RÓTULOS («Remitente:», «Fecha:»…), no por los emojis, que cambian
# según el teclado (🏛 / 🏛️).

_RE_ADORNO = re.compile(r"^[^\w«\"“”(¡¿\-]+")
_ROTULOS_RESUMEN = (
    "fecha del documento", "registro std", "dirigido a", "remitente", "convoca", "recibido", "participa",
    "asunto", "contenido", "detalle", "informaci[oó]n solicitada", "norma o dispositivo",
    "acci[oó]n requerida", "acci[oó]n previa", "plazo", "prioridad", "confirmaci[oó]n",
    "fecha", "hora", "lugar", "modalidad", "documento",
)
_RE_ROTULO_RESUMEN = re.compile(r"^(" + "|".join(_ROTULOS_RESUMEN) + r")\s*:\s*(.*)$", re.I)
_LISTAS_RESUMEN = ("contenido", "detalle", "informacion solicitada")
_RE_FECHA_DMA = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_RE_HORA = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(?:h\b|hrs?\b|horas\b)?\s*(a\.?\s*m\.?|p\.?\s*m\.?)?", re.I)


def _valor(v: str) -> str:
    """El valor de un campo sin comillas; «NO INDICA» es vacío."""
    v = _espacios(v or "").strip(" \"'«»“”")
    return "" if normalizar(v).startswith("no indica") else v


def _fecha_dma(v: str) -> str:
    m = _RE_FECHA_DMA.search(v or "")
    return _fecha_valida(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else ""


def _hora(v: str) -> str:
    """«15:00 h» → «15:00»; «6:30 p. m.» → «18:30». Vacío si no consta."""
    v = _valor(v)
    m = _RE_HORA.search(v) if v else None
    if not m:
        return ""
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    sufijo = (m.group(3) or "").replace(" ", "").replace(".", "").lower()
    if sufijo == "pm" and h < 12:
        h += 12
    elif sufijo == "am" and h == 12:
        h = 0
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else ""


def _registro_std(v: str) -> str:
    """«N.° 0002420835» → «2420835»; un número que no es del STD (una proposición, un
    código raro) queda vacío."""
    m = re.match(r"^(?:N\s*[.°º]*\s*)?0*(\d{4,})\b", _valor(v), re.I)
    return m.group(1)[:20] if m else ""


def _via_de(v: str) -> str:
    n = normalizar(v)
    if "correo" in n:
        return "correo"
    if "mesa de partes" in n:
        return "mesa_partes"
    if "std" in n or "tramite" in n:
        return "std"
    return "otro" if n else ""


def _atencion_de_accion(accion: str) -> str:
    """La acción requerida del resumen («Gestionar ante el MEF…») como tipo de atención."""
    n = normalizar(accion)
    if not n or n.startswith("ninguna"):
        return "conocimiento"
    if re.search(r"\b(agend\w*|reunion|audiencia|cita|asistir|asistencia|coordinar fecha|participar)\b", n):
        return "agendar"
    if re.search(r"\b(interced\w*|gestionar|articular|intermedia\w*|buenos oficios)\b", n):
        return "interceder"
    if re.search(r"\b(opinion|pronunci\w*|posicion)\b", n):
        return "emitir_opinion"
    return "responder"


def _tipo_evento(titulo: str, convoca: str) -> str:
    n = normalizar(f"{titulo} {convoca}")
    if "pleno" in n:
        return "pleno"
    if "comision" in n and "sesion" in n:
        return "comision"
    return "externa"


def leer_resumen(texto: str) -> dict:
    """El mensaje del prompt de recepción → {tipo, ficha, evento, avisos}. `ficha` trae
    solo los campos que el mensaje dice (lo demás queda como estaba); `evento`, en una
    AGENDA con fecha, los datos para la Agenda; `tipo`: 'comunicado' | 'agenda' | ''."""
    tipo = ""
    campos: dict[str, str] = {}
    listas: dict[str, list[str]] = {}
    actual = ""
    documento_suelto = titulo = ""
    for bruta in (texto or "").splitlines():
        linea = _RE_ADORNO.sub("", bruta.strip()).strip()
        if not linea:
            continue
        n = normalizar(linea)
        if n.startswith("enrutamiento") or "no copiar al grupo" in n or n.startswith("———"):
            continue
        if n.startswith("nuevo documento recibido"):
            tipo, actual = "comunicado", ""
            continue
        if n.startswith("agenda") and "nueva actividad" in n:
            tipo, actual = "agenda", ""
            continue
        m = _RE_ROTULO_RESUMEN.match(linea)
        if m:
            actual = normalizar(m.group(1))
            campos[actual] = m.group(2).strip()
            if actual in _LISTAS_RESUMEN and campos[actual]:
                listas.setdefault(actual, []).append(campos[actual])
            continue
        if actual in _LISTAS_RESUMEN:
            listas.setdefault(actual, []).append(linea.lstrip("-• ").strip())
        elif actual == "asunto":
            campos["asunto"] = f"{campos['asunto']} {linea}".strip()
        elif not actual and bruta.lstrip().startswith("📄") and not documento_suelto:
            documento_suelto = linea
        elif not actual and bruta.lstrip().startswith("📌") and not titulo:
            titulo = linea
    if not tipo and campos:
        tipo = "agenda" if {"convoca", "hora", "lugar"} & set(campos) else "comunicado"
    avisos: list[str] = []
    if not campos:
        return {"tipo": "", "ficha": {}, "evento": None,
                "avisos": ["No se reconoció el formato del resumen del grupo (📄 Remitente, 📅 Fecha, 📝 Asunto…)."]}

    documento = _valor(campos.get("documento", "") or documento_suelto)
    remitente = _valor(campos.get("remitente", "") or campos.get("convoca", ""))
    cargo = ""
    for sep in (" — ", " – ", " - "):
        if sep in remitente:
            remitente, cargo = (x.strip() for x in remitente.split(sep, 1))
            break
    asunto = _valor(campos.get("asunto", ""))
    lineas = [x for c in ("contenido", "detalle") for x in listas.get(c, []) if _valor(x)]
    if listas.get("informacion solicitada"):
        lineas.append("Información solicitada: " + "; ".join(_valor(x) for x in listas["informacion solicitada"] if _valor(x)))
    if _valor(campos.get("norma o dispositivo", "")):
        lineas.append("Norma: " + _valor(campos["norma o dispositivo"]))
    accion = _valor(campos.get("accion requerida", ""))
    previa = _valor(campos.get("accion previa", ""))
    if accion and not normalizar(accion).startswith("ninguna"):
        lineas.append("Acción requerida: " + accion)
    if previa and not normalizar(previa).startswith("ninguna"):
        lineas.append("Acción previa: " + previa)

    ficha: dict = {}
    if documento:
        ficha["documento"] = documento[:300]
    if remitente:
        ficha["remitente"], ficha["remitente_cargo"] = remitente[:300], cargo[:300]
    if asunto:
        ficha["asunto"] = asunto
    if lineas:
        ficha["resumen"] = "\n".join(f"- {x}" for x in lineas)
    for clave, campo in (("fecha_documento", "fecha del documento"), ("fecha_recepcion", "recibido")):
        f = _fecha_dma(campos.get(campo, ""))
        if f:
            ficha[clave] = f
    if _via_de(campos.get("recibido", "")):
        ficha["via"] = _via_de(campos["recibido"])
    if _registro_std(campos.get("registro std", "")):
        ficha["std_numero"] = _registro_std(campos["registro std"])

    evento = None
    if tipo == "agenda":
        ficha["clase"] = "citacion" if "citaci" in normalizar(f"{documento} {asunto}") else "invitacion"
        ficha["atencion"] = "agendar"
        confirmacion = _fecha_dma(campos.get("confirmacion", ""))
        if confirmacion:
            ficha["plazo"] = confirmacion
        fecha = _fecha_dma(campos.get("fecha", ""))
        if not fecha:
            avisos.append("La actividad no tiene fecha: no se propone el evento de la Agenda.")
        else:
            hora = _hora(campos.get("hora", ""))
            nombre = _valor(titulo) or asunto or documento or "Actividad"
            modalidad = normalizar(_valor(campos.get("modalidad", "")))
            descripcion = [f"Convoca: {_valor(campos.get('convoca', ''))}"] if _valor(campos.get("convoca", "")) else []
            descripcion += [f"- {x}" for x in listas.get("detalle", []) if _valor(x)]
            if previa and not normalizar(previa).startswith("ninguna"):
                descripcion.append(f"Acción previa: {previa}")
            evento = {
                "titulo": nombre[:300],
                "tipo": _tipo_evento(nombre, _valor(campos.get("convoca", ""))),
                "inicio": f"{fecha}T{hora or '00:00'}:00",
                "todo_el_dia": not hora,
                "lugar": _valor(campos.get("lugar", ""))[:300],
                "modalidad": "virtual" if modalidad.startswith("virtual") else "mixta" if modalidad.startswith("mixta") else "presencial",
                "descripcion": "\n".join(descripcion),
            }
            if not hora:
                avisos.append("La hora no consta: el evento queda como de todo el día.")
    else:
        if accion or "accion requerida" in campos:
            ficha["atencion"] = _atencion_de_accion(accion)
        plazo = _fecha_dma(campos.get("plazo", ""))
        if plazo:
            ficha["plazo"] = plazo
        doc_clase = extraer_documento(documento)[1] if documento else ""
        if documento or asunto:
            ficha["clase"] = clase_de(f"{documento}\n{asunto}", doc_clase)
    return {"tipo": tipo, "ficha": ficha, "evento": evento, "avisos": avisos}


# --- 5. Word e imágenes a PDF, y partes de un mismo documento ----------------------------

IMAGENES = (".jpg", ".jpeg", ".png", ".webp")
OFIMATICA = (".docx", ".doc", ".odt", ".rtf")
ADMITIDOS = (".pdf", *OFIMATICA, *IMAGENES)


class ErrorConversion(Exception):
    """Un archivo que no se pudo pasar a PDF o unir; el mensaje es para la persona."""


def convertir_a_pdf(ruta: Path, carpeta: Path) -> Path:
    """El PDF de `ruta` (el mismo si ya lo es): las imágenes con Pillow, Word y similares
    con LibreOffice sin pantalla. El resultado queda en `carpeta`."""
    sufijo = ruta.suffix.lower()
    if sufijo == ".pdf":
        return ruta
    destino = carpeta / f"{ruta.stem}.pdf"
    if sufijo in IMAGENES:
        from PIL import Image, ImageOps

        try:
            with Image.open(ruta) as img:
                ImageOps.exif_transpose(img).convert("RGB").save(destino, "PDF", resolution=150)
        except OSError as e:
            raise ErrorConversion("La imagen está dañada o no se puede leer.") from e
        return destino
    if sufijo not in OFIMATICA:
        raise ErrorConversion("Solo PDF, Word o imágenes (JPG, PNG).")
    try:
        # Perfil propio: si alguien tiene LibreOffice abierto, el perfil compartido estaría bloqueado.
        subprocess.run(
            ["soffice", f"-env:UserInstallation=file://{carpeta}/perfil-libreoffice", "--headless",
             "--convert-to", "pdf", "--outdir", str(carpeta), str(ruta)],
            capture_output=True, timeout=180, check=True,
        )
    except FileNotFoundError as e:
        raise ErrorConversion("Falta LibreOffice en el servidor: convierta el Word a PDF y súbalo.") from e
    except (subprocess.SubprocessError, OSError) as e:
        raise ErrorConversion("No se pudo convertir el Word a PDF.") from e
    if not destino.is_file():
        raise ErrorConversion("No se pudo convertir el Word a PDF.")
    return destino


def unir_pdfs(rutas: list[Path], destino: Path) -> Path:
    """Las partes de un mismo envío (citación, agenda, proyectos…) en un solo PDF, en el
    orden dado. `pdfunite` es de poppler, como `pdftotext`."""
    try:
        subprocess.run(["pdfunite", *map(str, rutas), str(destino)], capture_output=True, timeout=300, check=True)
    except FileNotFoundError as e:
        raise ErrorConversion("Falta «pdfunite» (poppler-utils) en el servidor.") from e
    except (subprocess.SubprocessError, OSError) as e:
        raise ErrorConversion("No se pudieron unir los PDF (alguno está dañado o protegido).") from e
    return destino
