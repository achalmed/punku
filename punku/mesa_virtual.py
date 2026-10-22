"""MESA DE PARTES VIRTUAL (2026-10-12): lo que una persona o una entidad presenta al despacho
por la página pública `/mesa-de-partes`, sin cuenta (modelos_mesa.py; docs/arquitectura.md §28).

El pedido (Edison 2026-10-12): escalar Recibidos a una mesa de partes virtual «completa y fácil
de usar» para quien envía: llenar sus datos, subir sus documentos, recibir el cargo y seguir su
trámite, sin registrarse. Todo lo que llega es una `Entrada` de Recibidos (`via='mesa_virtual'`)
y el equipo la procesa como siempre; aquí vive lo que la mesa añade.

Reglas, con su fuente en la biblioteca (Calibre):
- La mesa de partes digital atiende 24 horas, los 7 días de la semana (TUO de la Ley 27444, D.S.
  006-2026-JUS, art. 117.1, texto de la Ley 31465 — calibre_id 10040). Así viene de fábrica
  (`horario.continua`, 2026-10-13, Edison: «la mesa de partes virtual atiende las 24 horas»): lo
  recibido se tiene por presentado el día y la hora en que llegó. Si el despacho fija un horario de
  atención (Administración), lo recibido fuera de él se tiene por presentado el día hábil siguiente
  (arts. 134 y 138; Directiva 07-2022-DGP/CR, 4.5 — calibre_id 10099). Un horario ya guardado se
  respeta: `continua` solo es verdadero de fábrica o si alguien lo elige.
- El cargo dice número de ingreso, naturaleza, fecha, hora, remitente, fojas y documentos
  acompañados (TUO, arts. 117.2 y 124.2).
- Se recibe todo, sin calificar (TUO, art. 124.1); lo incompleto se OBSERVA en un solo acto y se
  da un plazo de subsanación de dos días hábiles (TUO, arts. 125.1 y 125.6; la Directiva del
  Congreso da cinco: el plazo se configura). Sin subsanar, se tiene por no presentado (125.4).
- Los plazos en días son hábiles y se cuentan desde el día hábil siguiente (TUO, arts. 133-134);
  los no laborables, de los feriados nacionales y de los que el despacho registre (art. 137).

Partes PURAS (probadas en tests/test_mesa_virtual.py): días hábiles y horario, código de
seguimiento, validación de archivos por su firma de bytes, documentos de identidad, IP real tras
el proxy, límites por ventana y fichas de acceso. Después, lo que toca la base.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import re
import secrets
import shutil
import time
import unicodedata
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("qillqa.mesa_virtual")

# --- estados públicos ---------------------------------------------------------------------------

ESTADOS = ("recibido", "en_revision", "observado", "derivado", "atendido", "archivado")
ETIQUETA = {
    "recibido": "Recibido",
    "en_revision": "En revisión",
    "observado": "Observado",
    "derivado": "Derivado / En atención",
    "atendido": "Atendido",
    "archivado": "Archivado",
}
# Qué dice el seguimiento en cada estado (texto breve para el remitente).
EXPLICACION = {
    "recibido": "Su documento llegó y tiene número de expediente.",
    "en_revision": "El despacho está revisando su documento.",
    "observado": "Falta algo: lea la observación y subsánela dentro del plazo.",
    "derivado": "Su documento está en atención.",
    "atendido": "Su trámite fue atendido.",
    "archivado": "Su trámite fue archivado.",
}
# Acciones del equipo → estado público al que llevan.
ACCIONES = {"revision": "en_revision", "observar": "observado", "derivar": "derivado", "archivar": "archivado", "reabrir": "en_revision"}
# El estado de la Entrada de Recibidos que corresponde a cada estado público.
ESTADO_ENTRADA = {"recibido": "nueva", "en_revision": "en_atencion", "observado": "en_atencion", "derivado": "en_atencion",
                  "atendido": "respondida", "archivado": "archivada"}
CLASES_ARCHIVO = ("principal", "anexo", "subsanacion", "respuesta")

# --- configuración (tabla `ajustes`, clave `mesa_virtual`) -----------------------------------------

CLAVE_AJUSTE = "mesa_virtual"
TIPOS_POR_OMISION = ["Carta", "Oficio", "Solicitud", "Informe", "Invitación", "Memorial", "Otro"]
CONFIG_POR_OMISION: dict = {
    # Encendida o apagada: lo decide el registro de MÓDULOS (servicios/modulos.py, 2026-10-18), un
    # solo lugar de verdad; `cargar_config` pone aquí su valor efectivo y `guardar_config` no lo guarda.
    "activa": False,
    "nombre": "",                 # entidad receptora en el cargo; vacío = el nombre de la entidad del .env
    "presentacion": "Presente aquí sus documentos dirigidos al despacho, a cualquier hora. Recibirá un cargo con su código para seguir el trámite.",
    # `continua`: recibe y tiene por presentado a toda hora, todos los días (TUO 27444, art. 117.1).
    # inicio, fin y días: el horario de atención si el despacho lo fija (continua = False).
    "horario": {"continua": True, "inicio": "08:30", "fin": "17:30", "dias": [0, 1, 2, 3, 4]},
    "no_habiles": [],             # días no hábiles propios (AAAA-MM-DD), además de los feriados nacionales
    "plazo_subsanacion": 2,       # días hábiles (TUO 27444, art. 125.6)
    "max_archivo_mb": 20,
    "max_total_mb": 30,
    "max_anexos": 5,
    "envios_por_hora": 5,         # por IP
    "envios_por_dia": 20,         # por IP
    "tipos": TIPOS_POR_OMISION,
    "enlace_publico": "",         # el enlace permanente + /mesa-de-partes (para copiar y compartir)
}


def _hora(valor, defecto: str) -> str:
    v = str(valor or "").strip()
    return v if re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v) else defecto


def _entero(valor, defecto: int, minimo: int, maximo: int) -> int:
    try:
        n = int(valor)
    except (TypeError, ValueError):
        return defecto
    return max(minimo, min(maximo, n))


def normalizar_config(datos: dict | None) -> dict:
    """La configuración guardada (o enviada por el administrador), completa y dentro de límites
    sanos. Lo desconocido se ignora."""
    d = dict(datos or {})
    base = CONFIG_POR_OMISION
    h = d.get("horario") if isinstance(d.get("horario"), dict) else {}
    inicio = _hora(h.get("inicio"), base["horario"]["inicio"])
    fin = _hora(h.get("fin"), base["horario"]["fin"])
    if fin <= inicio:
        inicio, fin = base["horario"]["inicio"], base["horario"]["fin"]
    dias = sorted({int(x) for x in (h.get("dias") or []) if str(x).lstrip("-").isdigit() and 0 <= int(x) <= 6}) or list(base["horario"]["dias"])
    # Un horario guardado antes de existir `continua` (con inicio y fin) se respeta tal cual: solo
    # sin horario guardado vale el de fábrica (24 horas).
    if "continua" in h:
        continua = bool(h.get("continua"))
    else:
        continua = base["horario"]["continua"] if not h else False
    no_habiles = sorted({str(x)[:10] for x in (d.get("no_habiles") or []) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(x)[:10])})[:400]
    tipos = []
    for t in d.get("tipos") or []:
        t = re.sub(r"\s+", " ", str(t)).strip()[:60]
        if t and t not in tipos:
            tipos.append(t)
    max_archivo = _entero(d.get("max_archivo_mb"), base["max_archivo_mb"], 1, 40)
    enlace = str(d.get("enlace_publico") or "").strip()[:300]
    if enlace and not re.match(r"^https?://", enlace):
        enlace = ""
    return {
        "activa": bool(d.get("activa", base["activa"])),
        "nombre": re.sub(r"\s+", " ", str(d.get("nombre") or "")).strip()[:200],
        "presentacion": str(d.get("presentacion") if d.get("presentacion") is not None else base["presentacion"]).strip()[:600],
        "horario": {"continua": continua, "inicio": inicio, "fin": fin, "dias": dias},
        "no_habiles": no_habiles,
        "plazo_subsanacion": _entero(d.get("plazo_subsanacion"), base["plazo_subsanacion"], 1, 15),
        "max_archivo_mb": max_archivo,
        "max_total_mb": max(max_archivo, _entero(d.get("max_total_mb"), base["max_total_mb"], 1, 80)),
        "max_anexos": _entero(d.get("max_anexos"), base["max_anexos"], 0, 10),
        "envios_por_hora": _entero(d.get("envios_por_hora"), base["envios_por_hora"], 1, 100),
        "envios_por_dia": _entero(d.get("envios_por_dia"), base["envios_por_dia"], 1, 500),
        "tipos": tipos or list(base["tipos"]),
        "enlace_publico": enlace,
    }


# --- días hábiles y horario (puras) ----------------------------------------------------------------


def no_habiles(config: dict, desde: date, hasta: date) -> set[str]:
    """Fechas no hábiles de [desde, hasta]: feriados nacionales y días no laborables del sector
    público (servicios/feriados.py) más los que registró el despacho."""
    from punku import puertos

    fechas = {f["fecha"] for f in puertos.feriados_entre(desde, hasta) if f["tipo"] in ("feriado", "no_laborable")}
    return fechas | {f for f in config.get("no_habiles", []) if desde.isoformat() <= f <= hasta.isoformat()}


LABORABLES = [0, 1, 2, 3, 4]


def dias_habiles(config: dict) -> list[int]:
    """Los días de la semana hábiles para los PLAZOS. Con la mesa de 24 horas, de lunes a viernes
    (TUO 27444, art. 137: no son hábiles sábados, domingos ni feriados); con horario de atención,
    sus días."""
    h = config.get("horario", {})
    return LABORABLES if h.get("continua") else h.get("dias", LABORABLES)


def hora_cierre(config: dict) -> str:
    """Hasta qué hora vale el último día de un plazo: con la mesa de 24 horas, hasta las 23:59."""
    h = config.get("horario", {})
    return "23:59" if h.get("continua") else h.get("fin", "17:30")


def es_habil(d: date, config: dict, inhabiles: set[str] | None = None) -> bool:
    dias = dias_habiles(config)
    if d.weekday() not in dias:
        return False
    inhabiles = inhabiles if inhabiles is not None else no_habiles(config, d, d)
    return d.isoformat() not in inhabiles


def siguiente_habil(d: date, config: dict) -> date:
    """El primer día hábil DESPUÉS de `d`."""
    inh = no_habiles(config, d, d + timedelta(days=60))
    x = d + timedelta(days=1)
    for _ in range(366):
        if es_habil(x, config, inh):
            return x
        x += timedelta(days=1)
    return x


def sumar_habiles(d: date, n: int, config: dict) -> date:
    """El n-ésimo día hábil contado desde el día hábil siguiente a `d` (TUO 27444, arts. 133.1 y
    134.1): observar el lunes con 2 días → miércoles; el viernes → martes."""
    inh = no_habiles(config, d, d + timedelta(days=n * 3 + 60))
    x = d
    while n > 0:
        x += timedelta(days=1)
        if es_habil(x, config, inh):
            n -= 1
    return x


def momento_presentacion(local: datetime, config: dict) -> tuple[date, bool]:
    """(fecha en que se tiene por presentado, ¿llegó fuera del horario?). En un día hábil, antes
    del cierre cuenta ese día (antes de abrir también: es el primer momento hábil); después del
    cierre o en un día no hábil, el día hábil siguiente (TUO 27444, art. 138; Directiva
    07-2022-DGP/CR, 4.5). `local` está en la zona de la entidad. Con la mesa de 24 horas
    (`continua`), el mismo día en que llegó y nunca «fuera de horario» (art. 117.1)."""
    h = config.get("horario", {})
    if h.get("continua"):
        return local.date(), False
    hoy = local.date()
    hhmm = local.strftime("%H:%M")
    if es_habil(hoy, config) and hhmm < h.get("fin", "17:30"):
        return hoy, hhmm < h.get("inicio", "08:30")
    return siguiente_habil(hoy, config), True


def zona():
    from zoneinfo import ZoneInfo

    from punku.config import config

    try:
        return ZoneInfo(config.zona_horaria)
    except Exception:  # noqa: BLE001
        return timezone(timedelta(hours=-5))


def ahora_local() -> datetime:
    return datetime.now(zona())


# --- código de seguimiento y expediente (puras) -----------------------------------------------------

# Sin 0/O ni 1/I/L: se dicta por teléfono sin confusiones. 31 símbolos × 12 ≈ 59 bits al azar.
ALFABETO = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
LARGO_CODIGO = 12


def generar_codigo() -> str:
    crudo = "".join(secrets.choice(ALFABETO) for _ in range(LARGO_CODIGO))
    return "-".join(crudo[i:i + 4] for i in range(0, LARGO_CODIGO, 4))


def normalizar_codigo(texto: str) -> str:
    """«k7qf 9m2x-ht4p» → «K7QF-9M2X-HT4P»; vacío si no puede ser un código."""
    crudo = re.sub(r"[\s\-_.]", "", (texto or "").upper())
    if len(crudo) != LARGO_CODIGO or any(c not in ALFABETO for c in crudo):
        return ""
    return "-".join(crudo[i:i + 4] for i in range(0, LARGO_CODIGO, 4))


def texto_expediente(anio: int, correlativo: int) -> str:
    return f"MPV-{anio}-{correlativo:05d}"


# --- documentos de identidad (puras) ----------------------------------------------------------------

DOCS_PERSONA = ("DNI", "CE")


def limpiar_doc(numero: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", numero or "").upper()


def ruc_valido(ruc: str) -> bool:
    """RUC de 11 dígitos con su dígito verificador (módulo 11 de SUNAT)."""
    if not re.fullmatch(r"(10|15|16|17|20)\d{9}", ruc or ""):
        return False
    pesos = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    resto = 11 - sum(int(c) * p for c, p in zip(ruc[:10], pesos)) % 11
    return int(ruc[10]) == (resto - 10 if resto >= 10 else resto)


def error_doc(tipo: str, numero: str) -> str:
    """Vacío si el documento de identidad es válido; si no, el motivo en castellano llano."""
    n = limpiar_doc(numero)
    if tipo == "DNI":
        return "" if re.fullmatch(r"\d{8}", n) else "El DNI tiene 8 dígitos."
    if tipo == "CE":
        return "" if re.fullmatch(r"[0-9A-Z]{8,12}", n) else "El carné de extranjería tiene de 8 a 12 caracteres."
    if tipo == "RUC":
        return "" if ruc_valido(n) else "El RUC no es válido: revise los 11 dígitos."
    return "Tipo de documento no válido."


def enmascarar(numero: str) -> str:
    """«12345678» → «****5678»: el cargo y el seguimiento nunca muestran el número completo."""
    n = limpiar_doc(numero)
    return ("*" * max(0, len(n) - 4)) + n[-4:] if len(n) > 4 else n


def coincide_dato(dato: str, *validos: str) -> bool:
    """¿El dato que escribió quien consulta es uno de los documentos del trámite? Comparación en
    tiempo constante (no revela cuántos caracteres acertó)."""
    d = limpiar_doc(dato)
    ok = False
    for v in validos:
        v = limpiar_doc(v)
        if v and d:
            ok |= hmac.compare_digest(d.encode(), v.encode())
    return ok


# --- archivos (puras) -----------------------------------------------------------------------------

TIPOS_ARCHIVO = {"pdf": "application/pdf", "jpg": "image/jpeg", "png": "image/png"}


def tipo_por_firma(cabecera: bytes) -> str | None:
    """El tipo REAL del archivo por sus primeros bytes, no por su nombre."""
    if cabecera[:5] == b"%PDF-":
        return "pdf"
    if cabecera[:3] == b"\xff\xd8\xff":
        return "jpg"
    if cabecera[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return None


def error_archivo(clase: str, tipo: str | None, tamano: int, max_bytes: int) -> str:
    """Vacío si el archivo se admite en su lugar; si no, por qué. El documento principal solo PDF;
    anexos y subsanaciones, PDF, JPG o PNG."""
    if tamano <= 0:
        return "El archivo está vacío."
    if tamano > max_bytes:
        return f"Pesa más de {max_bytes // (1024 * 1024)} MB."
    if clase == "principal" and tipo != "pdf":
        return "El documento principal debe ser un PDF."
    if tipo is None:
        return "Solo se admiten PDF, JPG o PNG (se revisa el contenido, no el nombre)."
    return ""


def sanear_nombre(nombre: str, maximo: int = 90) -> str:
    """Nombre original → texto seguro para MOSTRAR (nunca es una ruta): sin carpetas, sin
    caracteres de control ni separadores, con su extensión."""
    base = Path(str(nombre or "").replace("\\", "/")).name
    base = unicodedata.normalize("NFC", base)
    base = re.sub(r"[\x00-\x1f\x7f/\\:*?\"<>|]+", "", base).strip(" .")
    if not base:
        return "archivo"
    if len(base) > maximo:
        p = Path(base)
        base = p.stem[: maximo - len(p.suffix)] + p.suffix
    return base


# --- IP real tras el proxy y límites (puras) ----------------------------------------------------------


def _ip(texto: str):
    try:
        ip = ipaddress.ip_address((texto or "").strip().strip("[]"))
    except ValueError:
        return None
    return ip.ipv4_mapped or ip if isinstance(ip, ipaddress.IPv6Address) else ip   # «::ffff:1.2.3.4» → 1.2.3.4


def ip_real(par: str, reenviado: str = "") -> str:
    """La IP de quien hace la petición. La API escucha solo en 127.0.0.1 y le llega todo por el
    proxy de la web (vite, que añade `X-Forwarded-For` con `xfwd`) y, desde internet, también por
    Tailscale Funnel. Solo si el par inmediato es local se cree a `X-Forwarded-For`, leída de
    DERECHA a izquierda saltando los saltos locales: lo que un cliente escriba a la izquierda no
    sirve para disfrazarse."""
    p = _ip(par)
    if p is None or not p.is_loopback:
        return str(p) if p else (par or "")
    for parte in reversed([x for x in (reenviado or "").split(",") if x.strip()]):
        ip = _ip(parte)
        if ip is None:
            break
        if ip.is_loopback:
            continue
        return str(ip)
    return str(p)


class Limitador:
    """Ventanas deslizantes en memoria (la API corre en un solo proceso). `permitir` cuenta el
    intento solo si cabe."""

    def __init__(self, maximo_claves: int = 20000):
        self._marcas: dict[str, deque] = {}
        self._maximo = maximo_claves

    def permitir(self, clave: str, maximo: int, ventana: float, ahora: float | None = None) -> bool:
        t = time.monotonic() if ahora is None else ahora
        cola = self._marcas.get(clave)
        if cola is None:
            if len(self._marcas) >= self._maximo:
                self._podar(t)
            cola = self._marcas.setdefault(clave, deque())
        while cola and t - cola[0] > ventana:
            cola.popleft()
        if len(cola) >= maximo:
            return False
        cola.append(t)
        return True

    def restantes(self, clave: str, maximo: int, ventana: float, ahora: float | None = None) -> int:
        t = time.monotonic() if ahora is None else ahora
        cola = self._marcas.get(clave) or deque()
        return max(0, maximo - sum(1 for x in cola if t - x <= ventana))

    def _podar(self, t: float) -> None:
        for k in [k for k, c in self._marcas.items() if not c or t - c[-1] > 86400]:
            del self._marcas[k]
        if len(self._marcas) >= self._maximo:  # aún lleno: se suelta la mitad más vieja
            for k in sorted(self._marcas, key=lambda k: self._marcas[k][-1] if self._marcas[k] else 0)[: self._maximo // 2]:
                del self._marcas[k]

    def vaciar(self) -> None:
        self._marcas.clear()


LIMITES = Limitador()
# Límites fijos de la consulta (los de envío se configuran).
CONSULTAS_POR_VENTANA = (30, 600.0)       # 30 consultas cada 10 minutos por IP
FALLIDAS_POR_VENTANA = (10, 900.0)        # 10 consultas fallidas cada 15 minutos por IP
SUBSANACIONES_POR_HORA = (10, 3600.0)
DESCARGAS_POR_VENTANA = (60, 600.0)
ENVIOS_GLOBALES_POR_DIA = 150             # todo el mundo junto: protege el disco
DISCO_LIBRE_MINIMO = 2 * 1024 ** 3        # con menos de 2 GB libres no se recibe (la laptop es el servidor)


def disco_suficiente(carpeta: Path, envio_max: int) -> bool:
    """¿Queda sitio para recibir? Al menos 2 GB libres y diez envíos del tamaño máximo."""
    try:
        return shutil.disk_usage(carpeta).free >= max(DISCO_LIBRE_MINIMO, 10 * envio_max)
    except OSError:
        return False


# --- fichas firmadas: formulario y acceso (puras) -----------------------------------------------------

ESPERA_MINIMA_FORMULARIO = 3.0       # segundos: un robot llena y envía al instante
VIGENCIA_FORMULARIO = 24 * 3600
VIGENCIA_ACCESO = 2 * 3600


def _clave(proposito: str) -> bytes:
    from punku.config import config

    # La sal es un valor FIJO (2026-10-22, al retirar el nombre viejo del código): cambiarla invalidaría las fichas y los
    # enlaces de seguimiento que ya tienen los ciudadanos.
    return hashlib.sha256(f"sgdp-mesa-virtual:{proposito}:{config.jwt_secret}".encode()).digest()


def ficha_formulario(ahora: float | None = None) -> str:
    """Se entrega al abrir el formulario y vuelve con el envío: prueba que pasó por la página y
    que tardó lo que tarda una persona (campo trampa aparte)."""
    t = str(int(ahora if ahora is not None else time.time()))
    firma = hmac.new(_clave("formulario"), t.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{t}.{firma}"


def error_ficha_formulario(ficha: str, ahora: float | None = None) -> str:
    t_txt, _, firma = (ficha or "").partition(".")
    if not t_txt.isdigit() or not firma:
        return "invalida"
    esperada = hmac.new(_clave("formulario"), t_txt.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(esperada, firma):
        return "invalida"
    edad = (ahora if ahora is not None else time.time()) - int(t_txt)
    if edad < ESPERA_MINIMA_FORMULARIO:
        return "rapida"
    if edad > VIGENCIA_FORMULARIO:
        return "vencida"
    return ""


def ficha_acceso(tramite_id: int, ahora: float | None = None) -> str:
    """Tras consultar con código y documento (o al enviar), una ficha de 2 horas para descargar el
    cargo y la respuesta y para subsanar, sin repetir datos personales en cada petición ni
    ponerlos en una URL. Clave PROPIA: no sirve como sesión del sistema."""
    import jwt

    t = int(ahora if ahora is not None else time.time())
    return jwt.encode({"mpv": int(tramite_id), "iat": t, "exp": t + VIGENCIA_ACCESO, "aud": "mesa-publica"},
                      _clave("acceso"), algorithm="HS256")


def tramite_de_acceso(ficha: str) -> int | None:
    import jwt

    try:
        carga = jwt.decode(ficha or "", _clave("acceso"), algorithms=["HS256"], audience="mesa-publica")
    except jwt.InvalidTokenError:
        return None
    v = carga.get("mpv")
    return int(v) if isinstance(v, int) else None


# --- carpetas ---------------------------------------------------------------------------------------


def raiz_mesa() -> Path:
    """`<archivo documental>/recibidos/entradas/mesa-virtual/`, junto a los PDF de Recibidos."""
    from punku.entradas import raiz_entradas

    return raiz_entradas() / "mesa-virtual"


def carpeta_recepcion() -> Path:
    """Donde se reciben los archivos mientras se validan (se limpia sola: nada vive aquí > 1 h)."""
    c = raiz_mesa() / ".recepcion"
    c.mkdir(parents=True, exist_ok=True)
    limite = time.time() - 3600
    for p in c.iterdir():
        try:
            if p.stat().st_mtime < limite:
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()
        except OSError:
            pass
    return c


def carpeta_tramite(expediente: str, recibido: date) -> Path:
    c = raiz_mesa() / recibido.isoformat()[:7] / re.sub(r"[^A-Z0-9\-]", "", expediente)
    c.mkdir(parents=True, exist_ok=True)
    return c


def relativa(ruta: Path) -> str:
    from punku.config import raiz as raiz_documentos

    return str(ruta.resolve().relative_to(raiz_documentos().resolve()))


def absoluta(archivo: str) -> Path | None:
    """Ruta absoluta de un archivo guardado (relativo a la raíz documental), sin salir de ella."""
    from punku.config import raiz as raiz_documentos

    if not archivo:
        return None
    raiz = raiz_documentos().resolve()
    ruta = (raiz / archivo).resolve()
    if raiz not in ruta.parents:
        return None
    return ruta if ruta.is_file() else None


def huella(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as fh:
        for trozo in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(trozo)
    return h.hexdigest()


def comprobar_contenido(ruta: Path, tipo: str) -> tuple[int | None, str]:
    """(páginas, motivo de rechazo): un PDF que pdfinfo no lee o una imagen que Pillow no abre se
    rechazan (archivo dañado o disfrazado)."""
    if tipo == "pdf":
        from tiqsi.pdf import contar_paginas

        paginas = contar_paginas(ruta)
        if not paginas:
            return None, "No se pudo leer el PDF: puede estar dañado."
        return paginas, ""
    try:
        from PIL import Image

        with Image.open(ruta) as im:
            im.verify()
        return 1, ""
    except Exception:  # noqa: BLE001
        return None, "No se pudo leer la imagen: puede estar dañada."


@dataclass
class Recibido:
    """Un archivo ya validado en la carpeta de recepción."""

    clase: str
    ruta: Path
    nombre: str
    tipo: str
    bytes: int
    paginas: int | None
    sha256: str


@dataclass
class Rechazo(Exception):
    """Un envío que no se acepta: el motivo va tal cual a la persona."""

    motivo: str
    codigo: int = 422
    campo: str = ""
    extra: dict = field(default_factory=dict)


async def recibir_archivo(subido, clase: str, carpeta: Path, max_bytes: int, total: list[int], max_total: int) -> Recibido:
    """Guarda lo subido leyendo por trozos (corta en cuanto pasa el límite), comprueba su firma de
    bytes y su contenido y calcula su huella. `total` es un acumulador [bytes del envío]."""
    import asyncio

    nombre = sanear_nombre(getattr(subido, "filename", "") or "archivo")
    campo = {"principal": "principal", "anexo": "anexos"}.get(clase, "archivos")
    destino = carpeta / f"{secrets.token_hex(8)}.subido"
    tam = 0
    cabecera = b""
    with destino.open("wb") as fh:
        while trozo := await subido.read(1024 * 1024):
            if not cabecera:
                cabecera = trozo[:16]
            tam += len(trozo)
            total[0] += len(trozo)
            if tam > max_bytes:
                raise Rechazo(f"«{nombre}» pesa más de {max_bytes // (1024 * 1024)} MB.", 413, campo)
            if total[0] > max_total:
                raise Rechazo(f"El envío pasa de {max_total // (1024 * 1024)} MB en total.", 413, campo)
            fh.write(trozo)
    tipo = tipo_por_firma(cabecera)
    motivo = error_archivo(clase, tipo, tam, max_bytes)
    if motivo:
        raise Rechazo(f"«{nombre}»: {motivo}", campo=campo)
    paginas, motivo = await asyncio.to_thread(comprobar_contenido, destino, tipo)
    if motivo:
        raise Rechazo(f"«{nombre}»: {motivo}", campo=campo)
    ext = "." + tipo
    if not nombre.lower().endswith((ext, ".jpeg") if tipo == "jpg" else ext):
        nombre = f"{Path(nombre).stem or 'archivo'}{ext}"
    return Recibido(clase, destino, nombre, tipo, tam, paginas, await asyncio.to_thread(huella, destino))


def nombre_en_disco(orden: int, clase: str, tipo: str) -> str:
    return f"{orden:02d}-{clase}.{tipo}"


# --- base de datos ----------------------------------------------------------------------------------


async def cargar_config(sesion) -> dict:
    """La configuración con `activa` (y `mensaje`, el que se muestra apagada) del registro de módulos."""
    from punku.modelos import AjustePunku

    fila = await sesion.get(AjustePunku, CLAVE_AJUSTE)
    return await cargar_config_con(sesion, normalizar_config(fila.valor if fila else {}))


async def guardar_config(sesion, datos: dict) -> dict:
    """Guarda lo propio de la mesa (horario, límites, tipos…). Encenderla o apagarla, y su mensaje,
    van por el registro de módulos (`PUT /api/modulos/mesa_virtual`)."""
    from punku.modelos import AjustePunku

    limpio = normalizar_config(datos)
    limpio.pop("activa", None)
    fila = await sesion.get(AjustePunku, CLAVE_AJUSTE)
    if fila is None:
        sesion.add(AjustePunku(clave=CLAVE_AJUSTE, valor=limpio))
    else:
        fila.valor = limpio
    return await cargar_config_con(sesion, limpio)


async def cargar_config_con(sesion, limpio: dict) -> dict:
    from punku import puertos

    m = await puertos.modulo("mesa_virtual")   # el registro de módulos, por «modulos.v1» (Punku P1a)
    return {**limpio, "activa": m["activo"], "mensaje": m["mensaje"]}


def nombre_receptor(cfg: dict) -> str:
    from punku.config import config

    return cfg.get("nombre") or getattr(config, "vite_nombre_despacho", "") or "Despacho parlamentario"


def auditar(sesion, ip: str, accion: str, detalle: str = "", tramite_id: int | None = None, navegador: str = "") -> None:
    """Registro de la página pública (sin commit: lo da quien llama)."""
    from punku.modelos import MesaAuditoria

    sesion.add(MesaAuditoria(ip=(ip or "")[:64], accion=accion[:30], detalle=(detalle or "")[:500],
                             tramite_id=tramite_id, navegador=(navegador or "")[:300]))
    log.info("mesa virtual · %s · %s · %s", accion, ip, (detalle or "")[:160])


async def envios_recientes(sesion, ip: str) -> tuple[int, int, int]:
    """(envíos de esta IP en la última hora, en el último día, de todos en el último día)."""
    from sqlalchemy import func, select

    from punku.modelos import MesaTramite

    ahora = datetime.now(timezone.utc)
    hora = (await sesion.execute(select(func.count()).select_from(MesaTramite).where(
        MesaTramite.ip == ip, MesaTramite.creado_en > ahora - timedelta(hours=1)))).scalar_one()
    dia = (await sesion.execute(select(func.count()).select_from(MesaTramite).where(
        MesaTramite.ip == ip, MesaTramite.creado_en > ahora - timedelta(days=1)))).scalar_one()
    todos = (await sesion.execute(select(func.count()).select_from(MesaTramite).where(
        MesaTramite.creado_en > ahora - timedelta(days=1)))).scalar_one()
    return hora, dia, todos


async def siguiente_correlativo(sesion, anio: int) -> int:
    from sqlalchemy import func, select

    from punku.modelos import MesaTramite

    # Candado por año en la transacción: dos envíos a la vez no toman el mismo número.
    from sqlalchemy import text

    await sesion.execute(text("SELECT pg_advisory_xact_lock(7311, :a)"), {"a": anio})
    actual = (await sesion.execute(select(func.max(MesaTramite.correlativo)).where(MesaTramite.anio == anio))).scalar_one()
    return (actual or 0) + 1


async def codigo_libre(sesion) -> str:
    from sqlalchemy import select

    from punku.modelos import MesaTramite

    for _ in range(10):
        c = generar_codigo()
        if (await sesion.execute(select(MesaTramite.id).where(MesaTramite.codigo == c))).first() is None:
            return c
    raise RuntimeError("No se encontró un código libre")


CLASE_ENTRADA = {"carta": "carta", "oficio": "oficio", "solicitud": "solicitud", "informe": "informe",
                 "invitacion": "invitacion", "citacion": "citacion"}


def clase_de_tipo(tipo: str) -> str:
    from punku.entradas import normalizar

    n = normalizar(tipo).split(" ")[0] if tipo else ""
    return CLASE_ENTRADA.get(n, "otro")


def mover(origen: Path, carpeta: Path, nombre: str) -> Path:
    from tiqsi.nombres import unico_en

    final = carpeta / unico_en(carpeta, nombre)
    shutil.move(str(origen), str(final))
    return final


def movimiento(sesion, tramite, accion: str, nota: str = "", publico: bool = True, usuario_id: int | None = None) -> None:
    from punku.modelos import MesaMovimiento

    sesion.add(MesaMovimiento(tramite_id=tramite.id, estado=tramite.estado, accion=accion, nota=(nota or "")[:4000],
                              publico=publico, usuario_id=usuario_id))


def datos_evento(tramite, entrada) -> dict:
    return {"asunto": entrada.asunto or "", "remitente": entrada.remitente or "", "clase": entrada.clase,
            "atencion": entrada.atencion, "plazo": entrada.plazo or "", "responsable_id": entrada.responsable_id,
            "std_numero": "", "via": "mesa_virtual", "expediente": tramite.expediente}


async def archivos_de(sesion, tramite_id: int) -> list:
    from sqlalchemy import select

    from punku.modelos import MesaArchivo

    return list((await sesion.execute(select(MesaArchivo).where(MesaArchivo.tramite_id == tramite_id)
                                      .order_by(MesaArchivo.id))).scalars())


async def movimientos_de(sesion, tramite_id: int, solo_publicos: bool = False) -> list:
    from sqlalchemy import select

    from punku.modelos import MesaMovimiento

    q = select(MesaMovimiento).where(MesaMovimiento.tramite_id == tramite_id)
    if solo_publicos:
        q = q.where(MesaMovimiento.publico.is_(True))
    return list((await sesion.execute(q.order_by(MesaMovimiento.id))).scalars())


async def tramite_de_entrada(sesion, entrada_id: int):
    from sqlalchemy import select

    from punku.modelos import MesaTramite

    return (await sesion.execute(select(MesaTramite).where(MesaTramite.entrada_id == entrada_id))).scalars().first()


def _hora_local(dt: datetime | None) -> str:
    return dt.astimezone(zona()).strftime("%Y-%m-%dT%H:%M") if dt else ""


def archivo_publico(a) -> dict:
    return {"id": a.id, "clase": a.clase, "nombre": a.nombre, "tipo": a.tipo, "bytes": a.bytes, "paginas": a.paginas,
            "sha256": a.sha256, "fecha": _hora_local(a.creado_en), "fuera_de_plazo": a.fuera_de_plazo}


def vista_publica(t, archivos: list, movimientos: list, cfg: dict) -> dict:
    """Lo que ve el remitente: nunca notas internas, nunca su documento completo."""
    hoy = ahora_local().date()
    plazo = t.plazo_subsanacion
    vencido = bool(plazo and t.estado == "observado" and hoy > plazo)
    respuestas = [archivo_publico(a) for a in archivos if a.clase == "respuesta"] if t.estado == "atendido" else []
    return {
        "expediente": t.expediente,
        "codigo": t.codigo,
        "estado": t.estado,
        "estado_texto": ETIQUETA.get(t.estado, t.estado),
        "explicacion": EXPLICACION.get(t.estado, ""),
        "recibido_en": _hora_local(t.recibido_en),
        "presentado_el": t.presentado_el.isoformat() if t.presentado_el else "",
        "fuera_de_horario": t.fuera_de_horario,
        "receptor": nombre_receptor(cfg),
        "remitente": {
            "tipo_persona": t.tipo_persona, "nombre": t.nombre, "doc_tipo": t.doc_tipo, "doc": enmascarar(t.doc_numero),
            "representante": t.representante, "cargo": t.cargo,
        },
        "documento": {"tipo": t.tipo_documento, "numero": t.numero_documento, "folios": t.folios, "asunto": t.asunto,
                      "referencia": t.referencia},
        "archivos": [archivo_publico(a) for a in archivos if a.clase != "respuesta"],
        "observacion": {"texto": t.observacion, "plazo": plazo.isoformat() if plazo else "", "vencido": vencido,
                        "hasta": hora_cierre(cfg)} if t.estado == "observado" else None,
        "puede_subsanar": t.estado == "observado",
        "respuestas": respuestas,
        "historia": [{"fecha": _hora_local(m.creado_en), "estado": m.estado, "accion": m.accion,
                      "texto": ETIQUETA_ACCION.get(m.accion, ETIQUETA.get(m.estado, m.estado)), "nota": m.nota}
                     for m in movimientos if m.publico],
        "max_archivo_mb": cfg["max_archivo_mb"],
        "max_total_mb": cfg["max_total_mb"],
    }


ETIQUETA_ACCION = {
    "recibido": "Recibido", "revision": "En revisión", "observado": "Observado", "subsanado": "Subsanación recibida",
    "derivado": "Derivado / En atención", "atendido": "Atendido", "archivado": "Archivado", "reabierto": "Reabierto",
    "directorio": "Remitente en el directorio",
}


def vista_interna(t, archivos: list, movimientos: list, usuarios: dict, cfg: dict) -> dict:
    """Lo que ve el equipo en Recibidos: todo, con los datos de contacto completos."""
    v = vista_publica(t, archivos, movimientos, cfg)
    v["remitente"] = {
        "tipo_persona": t.tipo_persona, "nombre": t.nombre, "doc_tipo": t.doc_tipo, "doc": t.doc_numero,
        "representante": t.representante, "representante_doc_tipo": t.representante_doc_tipo,
        "representante_doc": t.representante_doc, "cargo": t.cargo, "correo": t.correo, "telefono": t.telefono,
        "direccion": t.direccion,
    }
    v["documento"]["comentario"] = t.comentario
    v["archivos"] = [archivo_publico(a) | {"documento_id": a.documento_id} for a in archivos]
    v["respuestas"] = [archivo_publico(a) | {"documento_id": a.documento_id} for a in archivos if a.clase == "respuesta"]
    v["historia"] = [{"fecha": _hora_local(m.creado_en), "estado": m.estado, "accion": m.accion,
                      "texto": ETIQUETA_ACCION.get(m.accion, m.accion), "nota": m.nota, "publico": m.publico,
                      "usuario": usuarios.get(m.usuario_id, "") if m.usuario_id else ""} for m in movimientos]
    v["declaracion"] = t.declaracion or {}
    v["observacion"] = {"texto": t.observacion, "plazo": t.plazo_subsanacion.isoformat() if t.plazo_subsanacion else "",
                        "vencido": bool(t.plazo_subsanacion and t.estado == "observado" and ahora_local().date() > t.plazo_subsanacion),
                        "hasta": hora_cierre(cfg)} if t.estado == "observado" else None
    v["plazo_propuesto"] = sumar_habiles(ahora_local().date(), cfg["plazo_subsanacion"], cfg).isoformat()
    v["dias_subsanacion"] = cfg["plazo_subsanacion"]
    v["entrada_id"] = t.entrada_id
    return v


def poner_estado(tramite, entrada, estado: str) -> None:
    """Estado público y, a la par, el de la Entrada de Recibidos. Salir de «Observado» cierra la
    observación (queda en la historia)."""
    tramite.estado = estado
    if estado != "observado":
        tramite.observacion, tramite.plazo_subsanacion = "", None
    if entrada is None:
        return
    nuevo = ESTADO_ENTRADA.get(estado, entrada.estado)
    if estado == "recibido" and (entrada.responsable_id or entrada.respuesta_documento_id):
        nuevo = "en_atencion"
    ahora = datetime.now(timezone.utc)
    if nuevo == "archivada" and entrada.estado != "archivada":
        entrada.archivada_en = ahora
    if nuevo == "respondida" and entrada.estado != "respondida":
        entrada.respondida_en = ahora
    if nuevo in ("nueva", "en_atencion"):
        entrada.archivada_en = None
        entrada.respondida_en = None
    entrada.estado = nuevo
