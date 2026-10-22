"""tests/test_mesa_virtual.py — la mesa de partes virtual (2026-10-12; servicios/mesa_virtual.py).

Pruebas puras (sin base de datos): días hábiles y horario de atención, código de seguimiento,
documentos de identidad, validación de archivos por su firma de bytes, nombres saneados, IP real
tras el proxy, límites por ventana, fichas firmadas, el cargo en PDF y que la aplicación no deje
abierta ninguna ruta además de las públicas conocidas. Uso: cd backend && .venv/bin/python -m pytest -q
"""
import asyncio
import os
import shutil
import subprocess
from datetime import date, datetime

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:y@127.0.0.1/z")
os.environ.setdefault("JWT_SECRET", "prueba")

from punku import cargo_pdf  # noqa: E402
from punku import mesa_virtual as mv  # noqa: E402

CFG = mv.normalizar_config({})
# Un horario de atención GUARDADO antes de existir `continua` (como el de producción): se respeta.
CON_HORARIO = mv.normalizar_config({"horario": {"inicio": "08:30", "fin": "17:30", "dias": [0, 1, 2, 3, 4]}})


# --- configuración ------------------------------------------------------------------------------


def test_config_por_omision_con_plazo_del_tuo():
    # Encendida o apagada lo decide el registro de módulos (servicios/modulos.py); aquí, apagada.
    assert CFG["activa"] is False
    assert CFG["plazo_subsanacion"] == 2
    # De fábrica, 24 horas todos los días (TUO 27444, art. 117.1; Edison 2026-10-13).
    assert CFG["horario"] == {"continua": True, "inicio": "08:30", "fin": "17:30", "dias": [0, 1, 2, 3, 4]}
    assert "Otro" in CFG["tipos"]


def test_un_horario_ya_guardado_no_se_pisa():
    assert CON_HORARIO["horario"]["continua"] is False
    assert mv.normalizar_config({"horario": {"continua": True, "inicio": "08:30", "fin": "17:30"}})["horario"]["continua"] is True
    assert mv.normalizar_config({"horario": {"continua": False}})["horario"]["continua"] is False


def test_config_se_sanea():
    c = mv.normalizar_config({
        "activa": True, "horario": {"inicio": "18:00", "fin": "09:00", "dias": [9, "x", 5]},
        "max_archivo_mb": 999, "max_total_mb": 1, "plazo_subsanacion": 0, "no_habiles": ["2026-12-24", "mañana"],
        "tipos": ["  Carta ", "Carta", ""], "enlace_publico": "javascript:alert(1)", "desconocido": 1,
    })
    assert c["activa"] is True
    assert c["horario"]["inicio"] == "08:30" and c["horario"]["fin"] == "17:30"   # fin antes que inicio: vuelve al de fábrica
    assert c["horario"]["dias"] == [5]
    assert c["max_archivo_mb"] == 40 and c["max_total_mb"] == 40                  # el total nunca menor que un archivo
    assert c["plazo_subsanacion"] == 1
    assert c["no_habiles"] == ["2026-12-24"]
    assert c["tipos"] == ["Carta"]
    assert c["enlace_publico"] == ""
    assert "desconocido" not in c


# --- días hábiles y horario -----------------------------------------------------------------------


def _l(texto: str) -> datetime:
    return datetime.fromisoformat(texto)


# --- código y expediente ------------------------------------------------------------------------------


def test_codigo_aleatorio_legible_y_sin_ambiguos():
    codigos = {mv.generar_codigo() for _ in range(2000)}
    assert len(codigos) == 2000
    for c in list(codigos)[:50]:
        assert len(c) == 14 and c[4] == "-" and c[9] == "-"
        assert not set(c.replace("-", "")) & set("01OIL")


def test_normalizar_codigo():
    c = mv.generar_codigo()
    assert mv.normalizar_codigo(c.lower().replace("-", " ")) == c
    assert mv.normalizar_codigo("ABCD-EFGH-IJKL") == ""     # I y L no existen en el alfabeto
    assert mv.normalizar_codigo("123") == ""
    assert mv.texto_expediente(2026, 7) == "MPV-2026-00007"


# --- documentos de identidad ------------------------------------------------------------------------


def _ruc_con_verificador(base10: str) -> str:
    pesos = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    resto = 11 - sum(int(c) * p for c, p in zip(base10, pesos)) % 11
    return base10 + str(resto - 10 if resto >= 10 else resto)


def test_ruc_valido_por_digito_verificador():
    ruc = _ruc_con_verificador("2013131295")
    assert mv.ruc_valido(ruc)
    malo = ruc[:-1] + str((int(ruc[-1]) + 1) % 10)
    assert not mv.ruc_valido(malo)
    assert not mv.ruc_valido("30131312955")   # prefijo inexistente
    assert mv.error_doc("RUC", ruc) == ""
    assert "RUC" in mv.error_doc("RUC", malo)


def test_documentos_de_persona():
    assert mv.error_doc("DNI", "12345678") == ""
    assert mv.error_doc("DNI", "1234567") != ""
    assert mv.error_doc("CE", "001234567") == ""
    assert mv.error_doc("PAS", "x") != ""
    assert mv.enmascarar("12345678") == "****5678"
    assert mv.coincide_dato(" 12.345.678 ", "12345678")
    assert not mv.coincide_dato("12345679", "12345678", "")
    assert not mv.coincide_dato("", "12345678")


# --- archivos --------------------------------------------------------------------------------------


def test_tipo_por_firma_de_bytes():
    assert mv.tipo_por_firma(b"%PDF-1.7\n") == "pdf"
    assert mv.tipo_por_firma(b"\xff\xd8\xff\xe0abc") == "jpg"
    assert mv.tipo_por_firma(b"\x89PNG\r\n\x1a\nxxxx") == "png"
    assert mv.tipo_por_firma(b"<html><script>") is None
    assert mv.tipo_por_firma(b"MZ\x90\x00") is None


def test_error_archivo():
    mb = 1024 * 1024
    assert mv.error_archivo("principal", "pdf", 10, 5 * mb) == ""
    assert "PDF" in mv.error_archivo("principal", "png", 10, 5 * mb)
    assert mv.error_archivo("anexo", "png", 10, 5 * mb) == ""
    assert "Solo se admiten" in mv.error_archivo("anexo", None, 10, 5 * mb)
    assert "5 MB" in mv.error_archivo("anexo", "pdf", 6 * mb, 5 * mb)
    assert "vacío" in mv.error_archivo("anexo", "pdf", 0, 5 * mb)


def test_sanear_nombre_nunca_deja_rutas():
    assert mv.sanear_nombre("../../etc/passwd") == "passwd"
    assert mv.sanear_nombre("C:\\Users\\x\\carta.pdf") == "carta.pdf"
    assert mv.sanear_nombre("a\x00b<>|.pdf") == "ab.pdf"
    assert mv.sanear_nombre("...") == "archivo"
    largo = mv.sanear_nombre("x" * 300 + ".pdf")
    assert len(largo) <= 90 and largo.endswith(".pdf")


class _Subido:
    def __init__(self, nombre: str, datos: bytes):
        self.filename = nombre
        self._datos = datos

    async def read(self, n: int = -1) -> bytes:
        trozo, self._datos = (self._datos, b"") if n < 0 else (self._datos[:n], self._datos[n:])
        return trozo


def _pdf_valido() -> bytes:
    lz = cargo_pdf.Lienzo()
    lz.parrafo("Solicitud de prueba")
    return lz.pdf()


@pytest.mark.skipif(shutil.which("pdfinfo") is None, reason="sin poppler")
def test_recibir_archivo(tmp_path):
    mb = 1024 * 1024
    r = asyncio.run(mv.recibir_archivo(_Subido("../carta final.PDF", _pdf_valido()), "principal", tmp_path, mb, [0], 2 * mb))
    assert r.tipo == "pdf" and r.paginas == 1 and len(r.sha256) == 64 and r.nombre == "carta final.PDF"
    assert r.ruta.parent == tmp_path
    # Un HTML disfrazado de PDF se rechaza por su contenido.
    with pytest.raises(mv.Rechazo) as e:
        asyncio.run(mv.recibir_archivo(_Subido("oficio.pdf", b"<html>hola</html>"), "anexo", tmp_path, mb, [0], 2 * mb))
    assert "Solo se admiten" in e.value.motivo
    # Un «PDF» que solo tiene la cabecera no se puede leer.
    with pytest.raises(mv.Rechazo) as e:
        asyncio.run(mv.recibir_archivo(_Subido("x.pdf", b"%PDF-1.4\nbasura"), "principal", tmp_path, mb, [0], 2 * mb))
    assert "dañado" in e.value.motivo
    # Más grande que el límite: corta mientras lee.
    with pytest.raises(mv.Rechazo) as e:
        asyncio.run(mv.recibir_archivo(_Subido("g.pdf", b"%PDF-" + b"0" * (mb + 10)), "principal", tmp_path, mb, [0], 4 * mb))
    assert e.value.codigo == 413
    # El total del envío también.
    with pytest.raises(mv.Rechazo) as e:
        asyncio.run(mv.recibir_archivo(_Subido("p.pdf", _pdf_valido()), "anexo", tmp_path, mb, [2 * mb], 2 * mb))
    assert "en total" in e.value.motivo


# --- IP real y límites -------------------------------------------------------------------------------


def test_ip_real_tras_el_proxy():
    assert mv.ip_real("192.168.1.20", "1.2.3.4") == "192.168.1.20"             # sin proxy: no se cree a la cabecera
    assert mv.ip_real("127.0.0.1", "") == "127.0.0.1"
    assert mv.ip_real("127.0.0.1", "203.0.113.10, 127.0.0.1") == "203.0.113.10"  # Funnel → vite → API
    assert mv.ip_real("127.0.0.1", "6.6.6.6, 192.168.1.30") == "192.168.1.30"  # lo de la izquierda lo escribió el cliente
    assert mv.ip_real("127.0.0.1", "basura, 127.0.0.1") == "127.0.0.1"
    assert mv.ip_real("::1", "2800:200::1") == "2800:200::1"
    assert mv.ip_real("::ffff:127.0.0.1", "::ffff:203.0.113.10") == "203.0.113.10"   # IPv4 dentro de IPv6 (vite en doble pila)


def test_disco_suficiente(tmp_path, monkeypatch):
    import collections

    uso = collections.namedtuple("uso", "total used free")
    monkeypatch.setattr(mv.shutil, "disk_usage", lambda _: uso(100, 0, 3 * 1024 ** 3))
    assert mv.disco_suficiente(tmp_path, 30 * 1024 ** 2)
    assert not mv.disco_suficiente(tmp_path, 400 * 1024 ** 2)   # diez envíos de 400 MB no caben en 3 GB
    monkeypatch.setattr(mv.shutil, "disk_usage", lambda _: uso(100, 0, 1024 ** 3))
    assert not mv.disco_suficiente(tmp_path, 1024)


def test_limitador_por_ventana():
    lim = mv.Limitador()
    assert all(lim.permitir("a", 3, 60, ahora=t) for t in (0, 1, 2))
    assert not lim.permitir("a", 3, 60, ahora=3)
    assert lim.permitir("b", 3, 60, ahora=3)          # otra IP no se ve afectada
    assert lim.permitir("a", 3, 60, ahora=61.5)       # pasó la ventana
    assert lim.restantes("a", 3, 60, ahora=61.5) == 1   # quedan la marca de t=2 y la nueva


# --- fichas firmadas -----------------------------------------------------------------------------------


def test_ficha_del_formulario():
    f = mv.ficha_formulario(ahora=1000)
    assert mv.error_ficha_formulario(f, ahora=1001) == "rapida"
    assert mv.error_ficha_formulario(f, ahora=1010) == ""
    assert mv.error_ficha_formulario(f, ahora=1000 + 2 * 86400) == "vencida"
    assert mv.error_ficha_formulario(f.replace(".", ".0"), ahora=1010) == "invalida"
    assert mv.error_ficha_formulario("", ahora=1010) == "invalida"


# --- cargo en PDF ------------------------------------------------------------------------------------------


def _vista() -> dict:
    return {
        "expediente": "MPV-2026-00012", "codigo": "K7QF-9M2X-HT4P", "recibido_en": "2026-10-12T22:14",
        "presentado_el": "2026-10-13", "fuera_de_horario": True, "receptor": "Despacho de prueba",
        "remitente": {"tipo_persona": "natural", "nombre": "María Ñahui Quispe", "doc_tipo": "DNI", "doc": "****5678",
                      "representante": "", "cargo": ""},
        "documento": {"tipo": "Solicitud", "numero": "", "folios": 3, "asunto": "Pedido de información sobre el puente «Añaypampa» " * 3,
                      "referencia": ""},
        "archivos": [{"clase": "principal", "nombre": "solicitud.pdf", "tipo": "pdf", "bytes": 120_000, "paginas": 3,
                      "sha256": "a" * 64}],
    }


def test_cargo_pdf_es_un_pdf_con_los_datos():
    pdf = cargo_pdf.cargo(_vista(), "https://ejemplo.ts.net/mesa-de-partes")
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    if shutil.which("pdftotext"):
        texto = subprocess.run(["pdftotext", "-", "-"], input=pdf, capture_output=True).stdout.decode()
        assert "MPV-2026-00012" in texto and "K7QF-9M2X-HT4P" in texto
        assert "Ñahui" in texto and "«Añaypampa»" in texto and "13/10/2026" in texto


def test_partir_respeta_el_ancho():
    lineas = cargo_pdf.partir("palabra " * 80, 200, 10)
    assert all(cargo_pdf.ancho_texto(x, 10) <= 200 for x in lineas)
    assert len(cargo_pdf.partir("f" * 64, 100, 8.5, "F3")) > 1


# --- ninguna ruta abierta por descuido -------------------------------------------------------------------

# Rutas sin la dependencia de sesión que ya existían (cada una con su propia comprobación) y las de
# la mesa pública. Una ruta nueva sin sesión hace fallar esta prueba: hay que decidirlo a propósito.
PUBLICAS_CONOCIDAS = {
    "/api/health", "/api/auth/login", "/api/auth/clave", "/api/auth/olvide", "/api/colab/estado",
    "/api/fototeca/{foto_id}/video", "/api/agenda.ics",
    # El acuse del aviso push (2026-10-13): el service worker no tiene sesión; lo protege la firma HMAC del aviso.
    "/api/push/recibido",
    # Los lotes de uso (2026-10-19): `navigator.sendBeacon` no manda cabeceras; la sesión viaja en el
    # cuerpo y la API la valida como cualquier JWT (sin sesión válida, 204 y nada se guarda).
    "/api/uso",
    # El Observatorio de datos (Qhawana Q1, 2026-10-20): su página y su estado, públicos como antes /obs/ (indicadores
    # de fuentes oficiales; va en un marco, que no manda cabeceras).
    "/api/observatorio/estado", "/api/observatorio/plataforma.html",
    # El kit de transmisiones (Wayra, editores E1, 2026-10-20): OBS carga sus piezas por URL, sin sesión; no llevan datos.
    "/api/obs/video/obs-studio/{ruta:path}", "/api/obs/tokens/{archivo}",
    # El editor de fotos (Tullpu, editores E2a, 2026-10-20): sus páginas y su API las protege la cookie del editor, que da
    # `POST /api/fotos/sesion` con la ficha (el marco no manda cabeceras), como antes /estudio/; borrarla no pide nada.
    "/api/fotos", "/api/fotos/{ruta:path}", "/api/fotos/sesion",
    # El editor de videos (Kuyuy, E3), igual que el de fotos.
    "/api/videos", "/api/videos/{ruta:path}", "/api/videos/sesion",
    # El editor de piezas (Awana, E4a), igual.
    "/api/piezas/editor", "/api/piezas/editor/{ruta:path}", "/api/piezas/editor/sesion",
}


