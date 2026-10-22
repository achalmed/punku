"""CARGO DE RECEPCIÓN de la mesa de partes virtual en PDF (2026-10-12; servicios/mesa_virtual.py).

Un PDF sencillo y sin dependencias nuevas: texto con las fuentes estándar del formato (Helvetica
y Courier, que todo lector trae, con la codificación WinAnsi que cubre tildes, eñes y comillas
latinas). No pasa por LuaLaTeX a propósito: el cargo se emite al instante, a cualquier hora, desde
la página pública, y no debe depender del motor de los documentos oficiales ni del perfil del
despacho. Lo que dice lo fija el TUO de la Ley 27444, arts. 117.2 y 124.2 (número de ingreso,
naturaleza, fecha, hora, remitente, fojas y documentos acompañados).

`Lienzo` es puro (bytes en memoria) y se prueba en tests/test_mesa_virtual.py.
"""

from __future__ import annotations

import unicodedata

ANCHO, ALTO = 595.28, 841.89  # A4 en puntos
MARGEN = 56.0

# Anchos de Helvetica (milésimas de em) de los caracteres 32..126 (métricas estándar AFM).
_HELV = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
]
_ESPECIALES = {"«": 556, "»": 556, "—": 1000, "–": 556, "°": 400, "“": 333, "”": 333, "‘": 222, "’": 222, "·": 278, "•": 350}


def ancho_texto(texto: str, tam: float, fuente: str = "F1") -> float:
    """Ancho en puntos de `texto` a `tam` puntos. Courier es de ancho fijo; la negrita se aproxima
    un 8 % más ancha que la regular (solo sirve para partir líneas, con holgura)."""
    if fuente == "F3":
        return len(texto) * 0.6 * tam
    total = 0
    for c in texto:
        if c in _ESPECIALES:
            total += _ESPECIALES[c]
            continue
        base = unicodedata.normalize("NFKD", c)[:1] or c
        o = ord(base)
        total += _HELV[o - 32] if 32 <= o <= 126 else 556
    return total * tam / 1000 * (1.08 if fuente == "F2" else 1.0)


def partir(texto: str, ancho: float, tam: float, fuente: str = "F1") -> list[str]:
    """Parte un texto en líneas que caben en `ancho` (por palabras; una palabra más larga que la
    línea se corta a la fuerza: las huellas SHA-256 en Courier)."""
    salida: list[str] = []
    for parrafo in (texto or "").split("\n"):
        linea = ""
        for palabra in parrafo.split(" "):
            prueba = f"{linea} {palabra}" if linea else palabra
            if ancho_texto(prueba, tam, fuente) <= ancho:
                linea = prueba
                continue
            if linea:
                salida.append(linea)
            while ancho_texto(palabra, tam, fuente) > ancho and len(palabra) > 1:
                corte = len(palabra)
                while corte > 1 and ancho_texto(palabra[:corte], tam, fuente) > ancho:
                    corte -= 1
                salida.append(palabra[:corte])
                palabra = palabra[corte:]
            linea = palabra
        salida.append(linea)
    return salida


def _cadena(texto: str) -> bytes:
    crudo = texto.encode("cp1252", "replace")
    return b"(" + crudo.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


class Lienzo:
    """Páginas A4 de texto: títulos, pares rótulo-valor, párrafos y líneas."""

    def __init__(self) -> None:
        self.paginas: list[list[bytes]] = []
        self._nueva()

    def _nueva(self) -> None:
        self.paginas.append([])
        self.y = ALTO - MARGEN

    def _sitio(self, alto: float) -> None:
        if self.y - alto < MARGEN:
            self._nueva()

    def _texto(self, x: float, y: float, texto: str, tam: float, fuente: str, gris: float = 0.0) -> None:
        self.paginas[-1].append(
            b"BT %.3f g /%s %.1f Tf %.2f %.2f Td " % (gris, fuente.encode(), tam, x, y) + _cadena(texto) + b" Tj ET"
        )

    def linea(self, grosor: float = 0.6, gris: float = 0.75) -> None:
        self._sitio(8)
        self.y -= 4
        self.paginas[-1].append(b"%.3f G %.2f w %.2f %.2f m %.2f %.2f l S" % (gris, grosor, MARGEN, self.y, ANCHO - MARGEN, self.y))
        self.y -= 8

    def espacio(self, alto: float = 8) -> None:
        self.y -= alto

    def parrafo(self, texto: str, tam: float = 10, fuente: str = "F1", gris: float = 0.0, sangria: float = 0) -> None:
        interlinea = tam * 1.35
        for ln in partir(texto, ANCHO - 2 * MARGEN - sangria, tam, fuente):
            self._sitio(interlinea)
            self.y -= interlinea
            self._texto(MARGEN + sangria, self.y, ln, tam, fuente, gris)

    def titulo(self, texto: str, tam: float = 14) -> None:
        self.parrafo(texto, tam, "F2")

    def par(self, rotulo: str, valor: str, tam: float = 10, columna: float = 150, fuente_valor: str = "F1") -> None:
        """«Rótulo      valor que puede ocupar varias líneas»."""
        interlinea = tam * 1.4
        lineas = partir(valor or "—", ANCHO - 2 * MARGEN - columna, tam, fuente_valor)
        for i, ln in enumerate(lineas):
            self._sitio(interlinea)
            self.y -= interlinea
            if i == 0:
                self._texto(MARGEN, self.y, rotulo, tam, "F2", 0.3)
            self._texto(MARGEN + columna, self.y, ln, tam, fuente_valor)

    def pdf(self, titulo: str = "Cargo de recepción") -> bytes:
        objetos: list[bytes] = []

        def agregar(cuerpo: bytes) -> int:
            objetos.append(cuerpo)
            return len(objetos)

        catalogo = agregar(b"")  # se completa al final
        paginas_id = agregar(b"")
        fuentes = {
            "F1": agregar(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"),
            "F2": agregar(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"),
            "F3": agregar(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"),
        }
        recursos = b"<< /Font << " + b" ".join(b"/%s %d 0 R" % (k.encode(), v) for k, v in fuentes.items()) + b" >> >>"
        hijos = []
        total = len(self.paginas)
        for n, contenido in enumerate(self.paginas, 1):
            pie = b"BT 0.5 g /F1 8 Tf %.2f %.2f Td " % (MARGEN, MARGEN / 2) + _cadena(f"Página {n} de {total}") + b" Tj ET"
            flujo = b"\n".join(contenido + [pie])
            cont = agregar(b"<< /Length %d >>\nstream\n" % len(flujo) + flujo + b"\nendstream")
            hijos.append(agregar(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Resources %s /Contents %d 0 R >>"
                % (paginas_id, ANCHO, ALTO, recursos, cont)
            ))
        objetos[paginas_id - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % h for h in hijos), len(hijos))
        objetos[catalogo - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % paginas_id
        info = agregar(b"<< /Title " + _cadena(titulo) + b" /Producer (Qillqa) >>")
        salida = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        desplazamientos = []
        for i, cuerpo in enumerate(objetos, 1):
            desplazamientos.append(len(salida))
            salida += b"%d 0 obj\n" % i + cuerpo + b"\nendobj\n"
        xref = len(salida)
        salida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
        for d in desplazamientos:
            salida += b"%010d 00000 n \n" % d
        salida += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objetos) + 1, catalogo, info, xref)
        return bytes(salida)


def _fecha(iso: str) -> str:
    """«2026-10-12» → «12/10/2026»; «2026-10-12T22:14» → «12/10/2026 22:14»."""
    if not iso:
        return ""
    f = f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}"
    return f"{f} {iso[11:16]}" if len(iso) >= 16 else f


def _peso(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB" if n >= 1024 * 1024 else f"{max(1, round(n / 1024))} KB"


def cargo(v: dict, enlace: str = "") -> bytes:
    """El cargo a partir de la vista pública del trámite (mesa_virtual.vista_publica)."""
    lz = Lienzo()
    lz.parrafo(v.get("receptor", ""), 10, "F2", 0.35)
    lz.titulo("Cargo de recepción — Mesa de partes virtual", 15)
    lz.linea(1.2, 0.3)
    lz.par("Expediente", v["expediente"], 11, fuente_valor="F2")
    lz.par("Código de seguimiento", v["codigo"], 11, fuente_valor="F3")
    lz.par("Recibido", _fecha(v["recibido_en"]) + " (hora de Lima)")
    # Con la mesa de 24 horas lo presentado es lo recibido (TUO 27444, art. 117.1): la fila solo sale
    # si un horario de atención lo pasó a otro día.
    if v.get("presentado_el") and v["presentado_el"][:10] != (v.get("recibido_en") or "")[:10]:
        presentado = _fecha(v["presentado_el"])
        if v.get("fuera_de_horario"):
            presentado += " (llegó fuera del horario de atención)"
        lz.par("Se tiene por presentado el", presentado)
    lz.espacio(6)
    lz.parrafo("Remitente", 11, "F2")
    r = v["remitente"]
    lz.par("Nombre o razón social", r["nombre"])
    lz.par(r["doc_tipo"], r["doc"])
    if r.get("representante"):
        lz.par("Representante", r["representante"] + (f" ({r['cargo']})" if r.get("cargo") else ""))
    lz.espacio(6)
    lz.parrafo("Documento", 11, "F2")
    d = v["documento"]
    lz.par("Tipo y número", " ".join(x for x in (d["tipo"], d["numero"]) if x))
    lz.par("Folios", str(d["folios"]))
    lz.par("Asunto", d["asunto"])
    if d.get("referencia"):
        lz.par("Referencia", d["referencia"])
    lz.espacio(6)
    lz.parrafo("Archivos recibidos", 11, "F2")
    for i, a in enumerate(v["archivos"], 1):
        clase = {"principal": "Principal", "anexo": "Anexo", "subsanacion": "Subsanación"}.get(a["clase"], a["clase"])
        detalle = f"{a['nombre']} · {_peso(a['bytes'])}" + (f" · {a['paginas']} pág." if a.get("paginas") and a["tipo"] == "pdf" else "")
        lz.par(f"{i}. {clase}", detalle)
        lz.par("    SHA-256", a["sha256"], 8.5, fuente_valor="F3")
    lz.espacio(10)
    lz.linea()
    lz.parrafo(
        "Conserve este cargo. Para seguir su trámite, entre a la mesa de partes virtual"
        + (f" ({enlace})" if enlace else "")
        + ", elija «Seguir mi trámite» y escriba su código de seguimiento y su número de documento de identidad.",
        9, gris=0.25,
    )
    lz.parrafo(
        "La huella SHA-256 identifica cada archivo tal como llegó: cualquier cambio en el archivo cambia la huella. "
        "Constancia emitida automáticamente por la mesa de partes virtual.",
        8.5, gris=0.4,
    )
    return lz.pdf(f"Cargo {v['expediente']}")
