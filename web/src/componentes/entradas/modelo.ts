/**
 * BANDEJA DE ENTRADA (2026-10-06) — tipos, rótulos y colores de los documentos
 * RECIBIDOS (backend/app/api/entradas.py, servicios/entradas.py). Una sola fuente
 * para la página /recibidos, su panel de detalle, la subida y la tarjeta del Inicio.
 */
import { PALETA } from '@qillqa/tiqsi'

export type EstadoEntrada = 'nueva' | 'en_atencion' | 'respondida' | 'archivada'
export type Atencion = 'responder' | 'agendar' | 'emitir_opinion' | 'interceder' | 'conocimiento'
export type Clase = 'oficio' | 'carta' | 'solicitud' | 'invitacion' | 'citacion' | 'informe' | 'otro'
/** Qué es para el despacho (2026-10-18; `servicios/entradas.py::CATEGORIAS`). */
export type Categoria = 'comunicacion' | 'respuesta' | 'invitacion' | 'seguimiento' | 'pronunciamiento' | 'anexo'
export type Via = 'std' | 'correo' | 'mesa_partes' | 'mano' | 'otro' | 'mesa_virtual'

/** Lo que se edita de una ficha (igual al cuerpo de `PUT /api/entradas/{id}`). */
export interface DatosFicha {
  std_numero: string
  documento: string
  clase: Clase
  via: Via
  remitente: string
  remitente_cargo: string
  remitente_persona_id: number | null
  remitente_institucion_id: number | null
  fecha_documento: string
  fecha_recepcion: string
  asunto: string
  referencia: string
  resumen: string
  atencion: Atencion
  /** Categoría (2026-10-18); vacía = sin clasificar. `requiere_revision`: la propuso la IA con poca confianza o nadie la confirmó. */
  categoria?: Categoria | ''
  requiere_revision?: boolean
  /** El oficio PROPIO al que este recibido responde. */
  responde_a_documento_id?: number | null
  responsable_id: number | null
  plazo: string
  campana: string
  nota: string
}

export interface DocBreve {
  id: number
  numero: string
  estado: string
  asunto: string
}

export interface Entrada extends DatosFicha {
  id: number
  estado: EstadoEntrada
  responde_a?: DocBreve | null
  responsable: string
  remitente_persona: string
  remitente_institucion: string
  remitente_institucion_nombre: string
  nombre_original: string
  paginas: number | null
  bytes: number
  respuesta: DocBreve | null
  vencida: boolean
  por_vencer: boolean
  creado_por: string
  creado_en: string | null
  respondida_en: string | null
  archivada_en: string | null
  cita: string
  /** De dónde salió cada campo: 'documento' (reglas sobre el PDF), 'pegado' (prompt) o 'persona'. */
  origen_campos: Record<string, 'documento' | 'pegado' | 'persona'>
  /** Llegó por la mesa de partes virtual (2026-10-12): expediente y estado que ve el remitente. */
  mesa?: { expediente: string; estado: string; estado_texto: string; plazo_subsanacion: string; vencido: boolean } | null
}

export interface FichaCompleta extends Entrada {
  vinculos: (DocBreve & { tipo: string; fuente: string; contexto: string; relacion_id: number })[]
  tiene_pdf: boolean
  texto: string
}

/** La ficha automática que devuelve `POST /api/entradas/analizar`. */
export interface FichaAuto extends Omit<DatosFicha, 'via' | 'responsable_id' | 'nota'> {
  sin_texto: boolean
  avisos: string[]
}

export interface Analizado {
  nombre: string
  error?: string
  token?: string
  bytes?: number
  paginas?: number | null
  ficha?: FichaAuto
  duplicado?: { id: number | null; motivo: string } | null
  copia_de_descarga?: boolean
  /** Cuántos archivos se unieron en este PDF (`POST /api/entradas/unir`). */
  partes?: number
}

/** El evento que propone un pegado con agenda (cuerpo de `POST /api/agenda/eventos`). */
export interface EventoPropuesto {
  titulo: string
  tipo: string
  inicio: string
  fin?: string | null
  todo_el_dia: boolean
  lugar: string
  modalidad: string
  enlace?: string
  descripcion: string
  participa?: string[]
  recordatorio_minutos?: number | null
}

/** `propuestas` de `POST /api/entradas/pegar` (2026-10-11): lo que el servidor cruzó con la base. */
export interface PropuestasEntrada {
  remitente_persona_id?: number | null
  remitente_institucion_id?: number | null
  instituciones_candidatas?: { id: number; nombre: string }[]
  /** Otra entrada ya tiene ese n.º STD. */
  duplicado?: { id: number; asunto: string; estado: string; std_numero: string }
  /** El documento propio que la referencia cita: queda como «responde a» al registrar (2026-10-18). */
  responde_a?: DocBreve | null
  /** El oficio propio que lleva el expediente que el documento nombra. */
  expediente_doc?: DocBreve | null
  /** La reunión o actividad de la Agenda a la que da seguimiento. */
  reunion_existente?: { id: number; titulo: string; inicio: string } | null
  /** La categoría propuesta y sus alternativas (la persona confirma); `requiere_revision` si la confianza fue baja. */
  categoria_opciones?: string[]
  requiere_revision?: boolean
  evento?: EventoPropuesto | null
  /** El mismo evento ya está en la Agenda: se vincula en vez de crearlo otra vez. */
  evento_existente?: { id: number; titulo: string; inicio: string } | null
}

export interface ResumenEntradas {
  nuevas: number
  en_atencion: number
  por_vencer: number
  vencidas: number
  mias: number
  sin_responsable: number
  urgentes: Entrada[]
}

export const ESTADOS: { v: EstadoEntrada; t: string; color: string }[] = [
  { v: 'nueva', t: 'Nueva', color: PALETA.guinda },
  { v: 'en_atencion', t: 'En atención', color: PALETA.info },
  { v: 'respondida', t: 'Respondida', color: PALETA.exito },
  { v: 'archivada', t: 'Archivada', color: PALETA.archivado },
]
export const ATENCIONES: { v: Atencion; t: string; ayuda: string }[] = [
  { v: 'responder', t: 'Responder', ayuda: 'Pide algo: va un oficio de respuesta' },
  { v: 'agendar', t: 'Agendar', ayuda: 'Invitación, citación o pedido de reunión' },
  { v: 'emitir_opinion', t: 'Emitir opinión', ayuda: 'Piden la opinión del despacho' },
  { v: 'interceder', t: 'Interceder', ayuda: 'Piden gestionar ante otra entidad' },
  { v: 'conocimiento', t: 'Para conocimiento', ayuda: 'Informa o responde a un oficio propio' },
]
export const CATEGORIAS: { v: Categoria; t: string; ayuda: string }[] = [
  { v: 'comunicacion', t: 'Comunicación nueva', ayuda: 'Nada previo en el despacho' },
  { v: 'respuesta', t: 'Respuesta a un oficio propio', ayuda: 'Contesta algo que el despacho envió' },
  { v: 'invitacion', t: 'Invitación o citación', ayuda: 'Invita, cita o agenda una actividad' },
  { v: 'seguimiento', t: 'Seguimiento de expediente', ayuda: 'Continúa un trámite en curso' },
  { v: 'pronunciamiento', t: 'Pronunciamiento', ayuda: 'Posición de una institución o gremio' },
  { v: 'anexo', t: 'Anexo o informe', ayuda: 'Completa otro documento' },
]
export const categoriaDe = (v: string | undefined | null) => CATEGORIAS.find((c) => c.v === v)?.t ?? ''
export const CLASES: { v: Clase; t: string }[] = [
  { v: 'oficio', t: 'Oficio' },
  { v: 'carta', t: 'Carta' },
  { v: 'solicitud', t: 'Solicitud' },
  { v: 'invitacion', t: 'Invitación' },
  { v: 'citacion', t: 'Citación' },
  { v: 'informe', t: 'Informe' },
  { v: 'otro', t: 'Otro' },
]
export const VIAS: { v: Via; t: string }[] = [
  { v: 'std', t: 'STD del Congreso' },
  { v: 'correo', t: 'Correo' },
  { v: 'mesa_partes', t: 'Mesa de partes' },
  { v: 'mano', t: 'En mano' },
  { v: 'mesa_virtual', t: 'Mesa de partes virtual' },
  { v: 'otro', t: 'Otra' },
]

export const estadoDe = (v: string) => ESTADOS.find((e) => e.v === v) ?? ESTADOS[0]
export const atencionDe = (v: string) => ATENCIONES.find((a) => a.v === v)?.t ?? v
export const claseDe = (v: string) => CLASES.find((c) => c.v === v)?.t ?? v

/** «03/10/2026» de «2026-10-03» (vacío si no hay fecha). */
export const fechaCorta = (iso?: string | null) =>
  /^\d{4}-\d{2}-\d{2}/.test(iso ?? '') ? `${iso!.slice(8, 10)}/${iso!.slice(5, 7)}/${iso!.slice(0, 4)}` : ''

/** Cómo se dice el plazo: «vence hoy», «venció hace 3 días», «vence en 2 días». */
export function textoPlazo(plazo: string, hoy: string): string {
  if (!plazo) return ''
  const dias = Math.round((Date.parse(plazo) - Date.parse(hoy)) / 86_400_000)
  if (dias === 0) return 'vence hoy'
  if (dias === 1) return 'vence mañana'
  if (dias > 1) return `vence en ${dias} días`
  if (dias === -1) return 'venció ayer'
  return `venció hace ${-dias} días`
}

/** La ficha de la API como datos editables (lo que viaja al confirmar o guardar). */
export const datosDe = (e: Entrada | (FichaAuto & { via?: Via; responsable_id?: number | null; nota?: string })): DatosFicha => ({
  std_numero: e.std_numero ?? '',
  documento: e.documento ?? '',
  clase: (e.clase ?? 'otro') as Clase,
  via: (e.via ?? 'std') as Via,
  remitente: e.remitente ?? '',
  remitente_cargo: e.remitente_cargo ?? '',
  remitente_persona_id: e.remitente_persona_id ?? null,
  remitente_institucion_id: e.remitente_institucion_id ?? null,
  fecha_documento: e.fecha_documento ?? '',
  fecha_recepcion: e.fecha_recepcion ?? '',
  asunto: e.asunto ?? '',
  referencia: e.referencia ?? '',
  categoria: ((e as { categoria?: string }).categoria ?? '') as Categoria | '',
  requiere_revision: Boolean((e as { requiere_revision?: boolean }).requiere_revision),
  responde_a_documento_id: (e as { responde_a_documento_id?: number | null }).responde_a_documento_id ?? null,
  resumen: e.resumen ?? '',
  atencion: (e.atencion ?? 'conocimiento') as Atencion,
  responsable_id: e.responsable_id ?? null,
  plazo: e.plazo ?? '',
  campana: e.campana ?? '',
  nota: e.nota ?? '',
})
