"""Modelos de la MESA DE PARTES VIRTUAL (2026-10-12; servicios/mesa_virtual.py, api/mesa_publica.py).

Lo que una persona o una entidad presenta por la página pública `/mesa-de-partes`, sin cuenta.
Cada presentación es un TRÁMITE con su expediente correlativo (`MPV-2026-00001`, para el cargo) y
su CÓDIGO de seguimiento aleatorio (`K7QF-9M2X-HT4P`, que nunca es correlativo). El trámite crea
una `Entrada` de Recibidos con `via='mesa_virtual'`: el equipo la procesa con todo lo que ya
existe (responder, agendar, crear tarea, pegar el resultado del prompt, vincular). Aquí vive solo
lo que la mesa añade: el remitente identificado, los archivos con su huella, el estado PÚBLICO y
su historia (lo que ve el remitente) y el registro de auditoría de la página pública.

Desde Punku P1a (fase 10.2b, 2026-10-20) con su propia Base (`BasePunku`) y sin claves foráneas hacia Qillqa (la
cuenta, la persona, la institución y el documento se guardan como número): aquí vive también `Entrada`, el
documento recibido, que salió de `modelos.py`. Las crea servicios/punku_db.py. docs/arquitectura.md §28.
"""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from tiqsi.bandeja_sql import tabla_bandeja


class BasePunku(DeclarativeBase):
    """Las tablas de la Mesa de Partes (proyecto Punku; fase 10.2b, 2026-10-20): su `create_all` es el del módulo
    (servicios/punku_db.py), no el de la base documental."""


class Entrada(BasePunku):
    """Documento RECIBIDO en la bandeja de entrada (2026-10-06; servicios/entradas.py).

    Lo que llega al despacho sin que el despacho lo haya pedido o en respuesta a un
    oficio propio: cartas de gremios, pedidos de municipios, invitaciones, citaciones,
    respuestas de entidades. Es una entidad APARTE de `Documento` (docs/decisiones.md,
    2026-10-06): no se numera ni pasa por el flujo de redacción y firma; tiene su propio
    ciclo (nueva → en atención → respondida | archivada), un tipo de atención, un
    responsable y un plazo. Su PDF vive en el archivo documental
    (`<MDD_DOCUMENTOS>/recibidos/entradas/AAAA-MM/`), con la ruta RELATIVA a esa raíz.

    Los vínculos con los documentos propios son relaciones genéricas (`relaciones`,
    `doc:N` → `entrada:M`, tipo `responde`): las crea «Responder» y la conciliación
    automática cuando un oficio cita en su Referencia el número STD de la entrada."""

    __tablename__ = "entradas"

    id: Mapped[int] = mapped_column(primary_key=True)
    despacho_id: Mapped[int] = mapped_column(Integer, default=1)
    periodo: Mapped[str] = mapped_column(String(20), default="")
    # El PDF: ruta relativa a la raíz del archivo documental (config.raiz_documentos()).
    archivo: Mapped[str] = mapped_column(Text, default="")
    nombre_original: Mapped[str] = mapped_column(String(300), default="")
    # Huella del PDF: dos subidas del mismo archivo son la misma entrada.
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    paginas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Texto extraído del PDF (búsqueda); vacío si es un escaneo sin capa de texto.
    texto: Mapped[str] = mapped_column(Text, default="")
    # N.º de registro del STD del Congreso (7 dígitos, prefijo del nombre al descargarlo).
    std_numero: Mapped[str] = mapped_column(String(20), default="", index=True)
    # Tipo y número del documento de origen («Oficio N° 0456-2026-UGEL-H/D»).
    documento: Mapped[str] = mapped_column(String(300), default="")
    # oficio | carta | solicitud | invitacion | citacion | informe | otro
    clase: Mapped[str] = mapped_column(String(20), default="otro")
    # Qué es para el despacho (2026-10-18): comunicacion | respuesta | invitacion | seguimiento |
    # pronunciamiento | anexo; vacío = sin clasificar. `requiere_revision`: la categoría la propuso la IA con
    # poca confianza o nadie la confirmó. `responde_a_documento_id`: el oficio PROPIO al que este recibido
    # responde (lo contrario de `respuesta_documento_id`, que es el oficio propio que responde a este).
    categoria: Mapped[str] = mapped_column(String(30), default="")
    requiere_revision: Mapped[bool] = mapped_column(Boolean, default=False)
    responde_a_documento_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # std | correo | mesa_partes | mano | otro
    via: Mapped[str] = mapped_column(String(20), default="std")
    # Remitente: del directorio si coincide; si no, solo el texto.
    remitente: Mapped[str] = mapped_column(String(300), default="")
    remitente_cargo: Mapped[str] = mapped_column(String(300), default="")
    remitente_persona_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remitente_institucion_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Fechas como texto AAAA-MM-DD, como en el resto de la plataforma.
    fecha_documento: Mapped[str] = mapped_column(String(10), default="")
    fecha_recepcion: Mapped[str] = mapped_column(String(10), default="")
    asunto: Mapped[str] = mapped_column(Text, default="")
    referencia: Mapped[str] = mapped_column(Text, default="")
    resumen: Mapped[str] = mapped_column(Text, default="")
    # responder | agendar | emitir_opinion | interceder | conocimiento
    atencion: Mapped[str] = mapped_column(String(20), default="conocimiento")
    responsable_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plazo: Mapped[str] = mapped_column(String(10), default="")
    # nueva | en_atencion | respondida | archivada
    estado: Mapped[str] = mapped_column(String(20), default="nueva", index=True)
    # Grupo de cartas iguales (p. ej. la campaña de los sindicatos sobre un PL).
    campana: Mapped[str] = mapped_column(String(160), default="", index=True)
    # El oficio propio que la responde (también está en `relaciones`; esto es el atajo).
    respuesta_documento_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nota: Mapped[str] = mapped_column(Text, default="")
    creado_por: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    respondida_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archivada_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Cuándo se avisó de que venció el plazo sin respuesta (un aviso por vencimiento).
    aviso_vencida_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # De dónde salió cada campo de la ficha (2026-10-11, «pegar resultado»): {campo: 'documento' (reglas
    # sobre el PDF) | 'pegado' (resultado de un prompt, aplicado por una persona) | 'persona'}.
    origen_campos: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")




class MesaTramite(BasePunku):
    """Un documento presentado por la mesa de partes virtual."""

    __tablename__ = "mesa_tramites"
    __table_args__ = (UniqueConstraint("anio", "correlativo", name="mesa_tramites_expediente_unico"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    despacho_id: Mapped[int] = mapped_column(Integer, default=1)
    entrada_id: Mapped[int | None] = mapped_column(ForeignKey("entradas.id", ondelete="SET NULL"), nullable=True, index=True)
    # Expediente correlativo por año (para el cargo) y código de seguimiento aleatorio (para seguirlo).
    anio: Mapped[int] = mapped_column(Integer)
    correlativo: Mapped[int] = mapped_column(Integer)
    expediente: Mapped[str] = mapped_column(String(30), unique=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    # Remitente: 'natural' (DNI o carné de extranjería) o 'juridica' (RUC y representante).
    tipo_persona: Mapped[str] = mapped_column(String(10), default="natural")
    doc_tipo: Mapped[str] = mapped_column(String(10), default="DNI")
    doc_numero: Mapped[str] = mapped_column(String(20), default="", index=True)
    nombre: Mapped[str] = mapped_column(String(300), default="")           # nombres y apellidos, o razón social
    representante: Mapped[str] = mapped_column(String(200), default="")
    representante_doc_tipo: Mapped[str] = mapped_column(String(10), default="")
    representante_doc: Mapped[str] = mapped_column(String(20), default="")
    cargo: Mapped[str] = mapped_column(String(200), default="")
    correo: Mapped[str] = mapped_column(String(200), default="")
    telefono: Mapped[str] = mapped_column(String(30), default="")
    direccion: Mapped[str] = mapped_column(String(300), default="")
    # El documento.
    tipo_documento: Mapped[str] = mapped_column(String(60), default="")
    numero_documento: Mapped[str] = mapped_column(String(120), default="")
    folios: Mapped[int] = mapped_column(Integer, default=1)
    asunto: Mapped[str] = mapped_column(Text, default="")
    comentario: Mapped[str] = mapped_column(Text, default="")
    referencia: Mapped[str] = mapped_column(String(300), default="")
    # Cuándo llegó (instante real) y desde cuándo se tiene por presentado (horario y días hábiles).
    recibido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    presentado_el: Mapped[date] = mapped_column(Date)
    fuera_de_horario: Mapped[bool] = mapped_column(Boolean, default=False)
    # Declaración jurada de veracidad y consentimiento de datos personales (Ley 29733): cuándo y qué texto.
    declaracion: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Estado PÚBLICO: recibido | en_revision | observado | derivado | atendido | archivado.
    estado: Mapped[str] = mapped_column(String(20), default="recibido", index=True)
    # Observación vigente: qué subsanar y hasta cuándo (día hábil).
    observacion: Mapped[str] = mapped_column(Text, default="")
    plazo_subsanacion: Mapped[date | None] = mapped_column(Date, nullable=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MesaArchivo(BasePunku):
    """Un archivo de un trámite: el principal, un anexo, una subsanación o la respuesta de la entidad."""

    __tablename__ = "mesa_archivos"

    id: Mapped[int] = mapped_column(primary_key=True)
    tramite_id: Mapped[int] = mapped_column(ForeignKey("mesa_tramites.id", ondelete="CASCADE"), index=True)
    # principal | anexo | subsanacion | respuesta
    clase: Mapped[str] = mapped_column(String(20), default="anexo")
    # Ruta RELATIVA a la raíz documental (config.raiz_documentos()); nunca la ruta que mandó el usuario.
    archivo: Mapped[str] = mapped_column(Text, default="")
    nombre: Mapped[str] = mapped_column(String(200), default="")         # nombre original saneado (solo para mostrar)
    tipo: Mapped[str] = mapped_column(String(10), default="pdf")         # pdf | jpg | png (por su firma de bytes)
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    paginas: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    # Respuesta tomada de un documento propio de Qillqa (firmado o generado), si fue así.
    documento_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Subsanación presentada después del plazo: el equipo decide (TUO 27444, art. 125.4).
    fuera_de_plazo: Mapped[bool] = mapped_column(Boolean, default=False)
    creado_por: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MesaMovimiento(BasePunku):
    """Un paso de la historia del trámite. `publico` = lo ve el remitente en el seguimiento."""

    __tablename__ = "mesa_movimientos"

    id: Mapped[int] = mapped_column(primary_key=True)
    tramite_id: Mapped[int] = mapped_column(ForeignKey("mesa_tramites.id", ondelete="CASCADE"), index=True)
    estado: Mapped[str] = mapped_column(String(20), default="")
    # recibido | revision | observado | subsanado | derivado | atendido | archivado | reabierto
    accion: Mapped[str] = mapped_column(String(20), default="")
    nota: Mapped[str] = mapped_column(Text, default="")
    publico: Mapped[bool] = mapped_column(Boolean, default=True)
    usuario_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MesaAuditoria(BasePunku):
    """Registro de la página pública: cada envío, consulta, descarga y rechazo, con la IP y el
    navegador. Para auditar abusos; no se muestra al remitente y nunca se borra desde la web."""

    __tablename__ = "mesa_auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    creado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    ip: Mapped[str] = mapped_column(String(64), default="", index=True)
    # envio | envio_rechazado | seguimiento | seguimiento_fallido | descarga | subsanacion | limite | trampa
    accion: Mapped[str] = mapped_column(String(30), default="")
    tramite_id: Mapped[int | None] = mapped_column(ForeignKey("mesa_tramites.id", ondelete="SET NULL"), nullable=True)
    detalle: Mapped[str] = mapped_column(String(500), default="")
    navegador: Mapped[str] = mapped_column(String(300), default="")


class AjustePunku(BasePunku):
    """Los ajustes de la Mesa de Partes (P1a): hoy, la configuración de la mesa de partes virtual. Antes vivía en
    `ajustes` de la plataforma; se copia aquí una vez (servicios/punku_db.py)."""

    __tablename__ = "punku_ajustes"

    clave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[dict] = mapped_column(JSONB, default=dict)


# Su bandeja de salida durable (Punku P1b, 2026-10-20; tiqsi.bandeja): lo que la Mesa de Partes cuenta («entrada.*», para
# las reglas de Qillqa y Tareas y Agenda) y los avisos de su campana («aviso.nuevo») entran en la MISMA transacción que el
# cambio; el repartidor del anfitrión los entrega al bus a lo sumo 2 s después (servicios/punku_eventos.py).
BANDEJA = tabla_bandeja(BasePunku.metadata, "punku_bandeja")


class SalidaPunku(BasePunku):
    """Una fila de la bandeja (para anotarla con `sesion.add`)."""

    __table__ = BANDEJA
