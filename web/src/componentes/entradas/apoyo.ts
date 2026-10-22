/**
 * Lo pequeño que la Mesa de Partes usa y antes tomaba de Qillqa (proyecto Punku; fase 10.2b P4, 2026-10-20): lo puro es
 * suyo (copiado, para no importar nada de la plataforma) y lo que solo tiene el anfitrión lo pide por nombre con
 * `servicio()` de Tiqsi web: si un módulo está encendido, el texto de un mensaje del chat, la constancia del pegado y
 * proponer o vincular un evento de la Agenda. Sola (la cáscara mínima), esos servicios no están y su ayuda no aparece.
 * Las piezas del anfitrión (la tabla del pegado, las actuaciones, el autocompletado del directorio) se pintan con
 * `<Pieza>` donde se usan.
 */
import { servicio } from '@qillqa/tiqsi'

// --- puro ----------------------------------------------------------------------------------------------------------

/** Hoy en AAAA-MM-DD con la hora de aquí (toISOString es la de Greenwich: de noche ya sería mañana). */
export const hoyIso = (): string => {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Alguien del equipo, como lo da `GET /api/auth/equipo`. */
export interface MiembroEquipo {
  id: number
  nombre_completo: string
  rol: string
  cargo?: string
}

/** Un celular peruano en 9 cifras («987654321»), o vacío. */
function celularPeruano(numero: string): string {
  let d = (numero ?? '').replace(/\D/g, '')
  if (d.startsWith('0051')) d = d.slice(2)
  if (d.length === 11 && d.startsWith('51')) d = d.slice(2)
  return d.length === 9 && d.startsWith('9') ? d : ''
}

/** «987654321» → «987 654 321»; otro número, tal cual. */
export function telefonoLegible(numero: string): string {
  const p = celularPeruano(numero)
  return p ? `${p.slice(0, 3)} ${p.slice(3, 6)} ${p.slice(6)}` : (numero ?? '').trim()
}

/** Lo que se aplicó de un pegado (la constancia que se registra al guardar). */
export interface PegadoAplicado {
  tipo: string
  version: number | null
  fuente: string
  texto: string
  campos_propuestos: Record<string, unknown>
  aceptadas: Set<string>
  rechazadas: string[]
}

/** Los campos aceptados de un pegado, marcados con su origen («pegado»). */
export const origenDePegado = (aceptadas: Set<string>): Record<string, 'pegado'> =>
  Object.fromEntries([...aceptadas].map((k) => [k, 'pegado' as const]))

// --- lo del anfitrión ----------------------------------------------------------------------------------------------

/** ¿Está encendido ese módulo del anfitrión? Sin el registro (sola), no. */
export const moduloActivo = (id: string): boolean => servicio<(m: string) => boolean>('modulos.activo')?.(id) ?? false

/** El texto de un mensaje del chat (un pegado que llega desde el chat). */
export async function textoDeMensaje(mid: number | string): Promise<string> {
  const traer = servicio<(m: number | string) => Promise<string>>('chat.texto_de_mensaje')
  if (!traer) throw new Error('El chat no está disponible.')
  return traer(mid)
}

/** La constancia de lo aplicado de un pegado (es secundaria: sin el anfitrión, no se guarda). */
export async function registrarPegado(datos: {
  tipo: string
  version?: number | null
  fuente?: string
  texto: string
  campos_propuestos: Record<string, unknown>
  campos_aplicados: Record<string, unknown>
  rechazados: string[]
  entidad: string
}): Promise<void> {
  await servicio<(d: typeof datos) => Promise<void>>('pegado.registrar')?.(datos)
}

/** ¿Se puede proponer un evento en la Agenda (Tareas y Agenda está, y encendido)? */
export const hayAgenda = (): boolean => Boolean(servicio('agenda.proponer_evento')) && moduloActivo('tareas')

/** Propone en la Agenda el evento que anuncia un recibido (o vincula el que ya existe). */
export async function proponerEvento(ev: Record<string, unknown> | null, existente: number | null, destino: string): Promise<void> {
  if (existente) await servicio<(id: number, d: string) => Promise<void>>('agenda.vincular_evento')?.(existente, destino)
  else if (ev) await servicio<(e: Record<string, unknown>, d: string) => Promise<void>>('agenda.proponer_evento')?.(ev, destino)
}

/** A dónde lleva algo del anfitrión («doc:12», «persona:3»: las referencias de la plataforma); null si no lo tiene. */
export const rutaDe = (clave: string): string | null =>
  servicio<(c: string) => string | null>('referencias.ruta')?.(clave) ?? null

/** ¿Hay documentos propios (Gestión documental) para responder o vincular? Sola, no. */
export const hayDocumentos = (): boolean => moduloActivo('documentos') && Boolean(servicio('documentos.buscar_vinculo'))

/** ¿Hay Tareas y Agenda para agendar o crear una tarea desde el recibido? Sola, no. */
export const hayTareas = (): boolean => moduloActivo('tareas')

/** Un documento propio por su número o asunto, para vincularlo como respuesta (del anfitrión). */
export async function buscarDocumentos<T>(q: string): Promise<T[]> {
  return (await servicio<(q: string) => Promise<T[]>>('documentos.buscar_vinculo')?.(q)) ?? []
}
