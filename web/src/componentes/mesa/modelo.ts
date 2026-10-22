/**
 * MESA DE PARTES VIRTUAL (2026-10-12) — cliente de la API PÚBLICA (backend/app/api/mesa_publica.py)
 * y sus tipos. Una sola fuente para las páginas públicas (/mesa-de-partes) y el panel del equipo.
 *
 * Sin sesión y sin cachés: no usa `api()` (que pone el token, guarda lecturas para el modo sin
 * conexión y cierra la sesión ante un 401). Todo va con `cache: 'no-store'`; el service worker no
 * toca /api/publico/. Las descargas son POST con la ficha de acceso en el cuerpo: ni el documento
 * de identidad ni la ficha viajan en la URL.
 */

/** `continua`: la mesa atiende las 24 horas, todos los días (de fábrica; TUO 27444, art. 117.1). */
export interface Horario { continua?: boolean; inicio: string; fin: string; dias: number[] }

export type EstadoPublico = 'recibido' | 'en_revision' | 'observado' | 'derivado' | 'atendido' | 'archivado'

export interface ConfigPublica {
  activa: boolean
  receptor: string
  mensaje?: string
  presentacion?: string
  horario?: Horario
  tipos?: string[]
  max_archivo_mb?: number
  max_total_mb?: number
  max_anexos?: number
  plazo_subsanacion?: number
  ahora?: string
  presentado_si_envia?: string
  fuera_de_horario?: boolean
  ficha?: string
}

export interface ArchivoTramite {
  id: number
  clase: 'principal' | 'anexo' | 'subsanacion' | 'respuesta'
  nombre: string
  tipo: 'pdf' | 'jpg' | 'png'
  bytes: number
  paginas: number | null
  sha256: string
  fecha: string
  fuera_de_plazo: boolean
  documento_id?: number | null
}

export interface PasoHistoria {
  fecha: string
  estado: EstadoPublico
  accion: string
  texto: string
  nota: string
  publico?: boolean
  usuario?: string
}

export interface Tramite {
  expediente: string
  codigo: string
  estado: EstadoPublico
  estado_texto: string
  explicacion: string
  recibido_en: string
  presentado_el: string
  fuera_de_horario: boolean
  receptor: string
  remitente: {
    tipo_persona: 'natural' | 'juridica'
    nombre: string
    doc_tipo: string
    doc: string
    representante: string
    cargo: string
    representante_doc_tipo?: string
    representante_doc?: string
    correo?: string
    telefono?: string
    direccion?: string
  }
  documento: { tipo: string; numero: string; folios: number; asunto: string; referencia: string; comentario?: string }
  archivos: ArchivoTramite[]
  observacion: { texto: string; plazo: string; vencido: boolean; hasta: string } | null
  puede_subsanar: boolean
  respuestas: ArchivoTramite[]
  historia: PasoHistoria[]
  max_archivo_mb: number
  max_total_mb: number
}

/** Lo que ve el equipo (api/mesa_virtual.py `GET /entradas/{id}`). */
export interface TramiteInterno extends Tramite {
  declaracion: { en?: string; texto?: string }
  plazo_propuesto: string
  dias_subsanacion: number
  entrada_id: number
}

export interface RespuestaTramite {
  tramite: Tramite
  acceso: string
  enlace?: string
  recibido?: boolean
}

export const BASE = '/api/publico/mesa'

/** Error de la API pública con el campo del formulario al que se refiere (si lo dice). */
export class ErrorMesa extends Error {
  campo: string
  estado: number
  constructor(mensaje: string, campo = '', estado = 0) {
    super(mensaje)
    this.campo = campo
    this.estado = estado
  }
}

async function error(r: Response): Promise<ErrorMesa> {
  const cuerpo = await r.json().catch(() => null)
  const d = (cuerpo as { detail?: unknown } | null)?.detail
  if (typeof d === 'string') return new ErrorMesa(d, '', r.status)
  const m = d as { mensaje?: string; campo?: string } | undefined
  if (m?.mensaje) return new ErrorMesa(m.mensaje, m.campo ?? '', r.status)
  if (r.status === 429) return new ErrorMesa('Demasiados intentos. Espere unos minutos.', '', 429)
  if (r.status >= 500) return new ErrorMesa('El sistema no responde ahora. Intente de nuevo en unos minutos.', '', r.status)
  return new ErrorMesa(`No se pudo completar (error ${r.status}).`, '', r.status)
}

async function pedir<T>(ruta: string, init: RequestInit = {}): Promise<T> {
  let r: Response
  try {
    r = await fetch(`${BASE}${ruta}`, { ...init, cache: 'no-store', credentials: 'omit' })
  } catch {
    throw new ErrorMesa('No hay conexión con el sistema. Revise su internet e intente de nuevo.')
  }
  if (!r.ok) throw await error(r)
  return (await r.json()) as T
}

export const leerConfig = () => pedir<ConfigPublica>('/config')

export const seguir = (codigo: string, documento: string) =>
  pedir<RespuestaTramite>('/seguimiento', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ codigo, documento }),
  })

/**
 * Envía un formulario multipart mostrando el avance de la subida (los archivos pesan y el celular
 * puede ir lento): fetch no informa del avance, XMLHttpRequest sí.
 */
export function enviarConAvance(ruta: string, datos: FormData, alAvanzar: (fraccion: number) => void): Promise<RespuestaTramite> {
  return new Promise((resolver, rechazar) => {
    const x = new XMLHttpRequest()
    x.open('POST', `${BASE}${ruta}`)
    x.upload.onprogress = (e) => e.lengthComputable && alAvanzar(e.loaded / e.total)
    x.onerror = () => rechazar(new ErrorMesa('Se cortó la conexión mientras se enviaba. Revise su internet e intente de nuevo.'))
    x.onload = async () => {
      const r = new Response(x.responseText, { status: x.status, headers: { 'Content-Type': 'application/json' } })
      if (x.status >= 200 && x.status < 300) resolver((await r.json()) as RespuestaTramite)
      else rechazar(await error(r))
    }
    x.send(datos)
  })
}

/** Descarga (POST con la ficha de acceso) y guarda el archivo con su nombre. */
export async function descargar(ruta: '/cargo' | '/respuesta', acceso: string, nombre: string, archivoId?: number): Promise<void> {
  let r: Response
  try {
    r = await fetch(`${BASE}${ruta}`, {
      method: 'POST', cache: 'no-store', credentials: 'omit',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acceso, archivo_id: archivoId ?? null }),
    })
  } catch {
    throw new ErrorMesa('No hay conexión con el sistema. Intente de nuevo.')
  }
  if (!r.ok) throw await error(r)
  const blob = await r.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = nombre
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 4000)
}

/** Copiar un texto: el portapapeles moderno pide https; en la red local se usa el camino antiguo. */
export async function copiarTexto(texto: string): Promise<boolean> {
  try {
    if (window.isSecureContext && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(texto)
      return true
    }
  } catch {
    /* sigue con el camino antiguo */
  }
  const area = document.createElement('textarea')
  area.value = texto
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  area.remove()
  return ok
}

export const ETIQUETA: Record<EstadoPublico, string> = {
  recibido: 'Recibido',
  en_revision: 'En revisión',
  observado: 'Observado',
  derivado: 'Derivado / En atención',
  atendido: 'Atendido',
  archivado: 'Archivado',
}

/** El camino habitual de un trámite, para la línea de tiempo. */
export const CAMINO: EstadoPublico[] = ['recibido', 'en_revision', 'derivado', 'atendido']

export const DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']

/** «lunes a viernes, de 08:30 a 17:30». */
export function textoHorario(h?: Horario): string {
  if (!h) return ''
  if (h.continua) return 'las 24 horas, todos los días'
  const d = [...h.dias].sort()
  const seguidos = d.length > 1 && d.every((x, i) => i === 0 || x === d[i - 1] + 1)
  const dias = seguidos ? `${DIAS[d[0]]} a ${DIAS[d[d.length - 1]]}` : d.map((x) => DIAS[x]).join(', ')
  return `${dias}, de ${h.inicio} a ${h.fin}`
}

/** ¿Se tiene por presentado otro día que el de su llegada? (solo con horario de atención: lo que
 *  llega fuera de él pasa al día hábil siguiente). Con la mesa de 24 horas, nunca. */
export function presentadoOtroDia(t: { recibido_en: string; presentado_el: string }): boolean {
  return Boolean(t.presentado_el && t.recibido_en && t.presentado_el.slice(0, 10) !== t.recibido_en.slice(0, 10))
}

/** «12/10/2026» o «12/10/2026 22:14» desde ISO. */
export function fechaHora(iso?: string): string {
  if (!iso) return ''
  const f = `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`
  return iso.length >= 16 ? `${f} ${iso.slice(11, 16)}` : f
}

export const peso = (n: number) => (n >= 1024 * 1024 ? `${(n / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)

/** Documento de identidad sin espacios, puntos ni guiones, en mayúsculas. */
export const soloDoc = (v: string) => v.replace(/[^0-9A-Za-z]/g, '').toUpperCase()

/** RUC de 11 dígitos con su dígito verificador (módulo 11 de SUNAT), igual que el servidor. */
export function rucValido(ruc: string): boolean {
  if (!/^(10|15|16|17|20)\d{9}$/.test(ruc)) return false
  const pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
  const resto = 11 - (pesos.reduce((s, p, i) => s + p * Number(ruc[i]), 0) % 11)
  return Number(ruc[10]) === (resto >= 10 ? resto - 10 : resto)
}

/** Vacío si el documento es válido; si no, el motivo (mismas reglas que servicios/mesa_virtual.py). */
export function errorDoc(tipo: string, n: string): string {
  if (tipo === 'DNI') return /^\d{8}$/.test(n) ? '' : 'El DNI tiene 8 dígitos.'
  if (tipo === 'CE') return /^[0-9A-Z]{8,12}$/.test(n) ? '' : 'El carné tiene de 8 a 12 caracteres.'
  return rucValido(n) ? '' : 'El RUC no es válido: revise los 11 dígitos.'
}

export const CLASE_ARCHIVO: Record<ArchivoTramite['clase'], string> = {
  principal: 'Documento principal',
  anexo: 'Anexo',
  subsanacion: 'Subsanación',
  respuesta: 'Respuesta',
}
