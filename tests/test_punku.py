"""tests/test_punku.py — la Mesa de Partes (proyecto Punku P1b, 2026-10-20): un documento propio que responde un
recibido cambia la entrada en la sesión de quien llama y deja su evento y su aviso en la bandeja de Punku; la relación
no la escribe Punku (la registra Qillqa, dueña del grafo)."""
import asyncio
from types import SimpleNamespace

from punku.modelos import SalidaPunku
from punku import entradas


class Sesion:
    def __init__(self):
        self.agregados = []

    def add(self, obj):
        self.agregados.append(obj)


def _entrada(**kw):
    base = dict(id=12, estado="nueva", respuesta_documento_id=None, respondida_en=None, responsable_id=4, creado_por=2,
                asunto="Pedido de información", documento="Oficio 15", std_numero="123", remitente="MEF")
    return SimpleNamespace(**{**base, **kw})


def test_un_oficio_firmado_responde_el_recibido_por_la_bandeja():
    s, e = Sesion(), _entrada()
    cambio = asyncio.run(entradas.vincular(s, e, {"id": 7, "estado": "FIRMADO"}, 3, "responder"))
    assert cambio and e.estado == "respondida" and e.respuesta_documento_id == 7 and e.respondida_en is not None
    assert all(isinstance(x, SalidaPunku) for x in s.agregados)
    tipos = [x.tipo for x in s.agregados]
    assert tipos == ["entrada.respondida", "aviso.nuevo"]
    evento, aviso = s.agregados
    assert evento.datos["entidad"] == "entrada:12" and evento.datos["datos"]["documento"] == "doc:7"
    assert evento.datos["usuario_id"] == 3 == evento.datos["emitido_por"] and evento.origen == "recibidos"
    assert aviso.datos["usuario_id"] == 4 and aviso.datos["destino"] == "entrada:12"


def test_un_borrador_solo_pone_el_recibido_en_atencion_y_no_avisa():
    s, e = Sesion(), _entrada()
    assert asyncio.run(entradas.vincular(s, e, {"id": 7, "estado": "BORRADOR"}, 3, "manual"))
    assert e.estado == "en_atencion" and not s.agregados


def test_nadie_se_avisa_a_si_mismo():
    s, e = Sesion(), _entrada(estado="en_atencion", responsable_id=3)
    asyncio.run(entradas.vincular(s, e, {"id": 7, "estado": "ENVIADO"}, 3, "manual"))
    assert [x.tipo for x in s.agregados] == ["entrada.respondida"]


def test_la_relacion_que_acompana_a_vincular():
    r = entradas.relacion_respuesta(_entrada(), 7, "referencia", 3)
    assert r == {"origen": "doc:7", "destino": "entrada:12", "tipo": "responde", "contexto": "referencia", "fuente": "auto",
                 "texto": entradas.texto_cita(_entrada()), "usuario_id": 3}


def test_la_bitacora_sale_por_la_bandeja_con_la_hora_del_cambio():
    from datetime import datetime

    from punku import eventos as punku_eventos

    s = Sesion()
    punku_eventos.bitacora(s, 3, "ajustes", "Configuración de la mesa de partes virtual")
    (fila,) = s.agregados
    assert fila.tipo == "bitacora.nueva" and fila.origen == "recibidos"
    assert fila.datos["usuario_id"] == 3 and fila.datos["accion"] == "ajustes"
    assert datetime.fromisoformat(fila.datos["fecha"]).tzinfo is not None


def test_el_nombre_del_recibido_cabe_en_el_limite_comun():
    from tiqsi.nombres import LIMITE

    n = entradas.nombre_archivo("2437652", "2026-10-03", "Sindicato Unitario de Trabajadores en la Educación " * 3,
                                "Delegación de facultades " * 10)
    assert n.startswith("ENT-2437652-2026-10-03_") and n.endswith(".pdf") and len(n) <= LIMITE
