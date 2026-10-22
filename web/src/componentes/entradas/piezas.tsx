/**
 * Las piezas del anfitrión que la Mesa de Partes pinta (proyecto Punku; fase 10.2b P4, 2026-10-20), con sus tipos: la
 * tabla de lo pegado (leer el resultado del prompt y elegir qué se aplica), las actuaciones del seguimiento y el
 * autocompletado del directorio. Las da Qillqa por nombre (`<Pieza>` de Tiqsi web); sola, no están: no se ofrece pegar
 * ni el seguimiento, y el remitente se escribe a mano.
 */
import type { ReactNode } from 'react'
import TextField from '@mui/material/TextField'
import { Pieza, hayPieza } from '@qillqa/tiqsi'
import type { PegadoAplicado } from './apoyo'

/** Lo que responde la lectura de un pegado (la parte que usa la Mesa de Partes). */
export interface RespuestaPegado<P = Record<string, unknown>> {
  campos: Record<string, unknown>
  propuestas?: P
}

export interface PropsPegarResultado<P> {
  /** Endpoint de pegado del módulo (`/api/entradas/pegar`). */
  ruta: string
  tipos: string[]
  actual: Record<string, unknown>
  cuerpoExtra?: Record<string, unknown>
  alAplicar: (campos: Record<string, unknown>, aplicado: PegadoAplicado, respuesta: RespuestaPegado<P>) => void
  propuestas?: (respuesta: RespuestaPegado<P>) => ReactNode
  abiertoAlInicio?: boolean
  compacto?: boolean
  etiquetaBoton?: string
  textoInicial?: string
}

export const hayPegado = (): boolean => hayPieza('pegado.Resultado')

export function PegarResultado<P = Record<string, unknown>>(props: PropsPegarResultado<P>) {
  return <Pieza pieza="pegado.Resultado" {...props} />
}

export const hayActuaciones = (): boolean => hayPieza('seguimiento.Actuaciones')

export function Actuaciones(props: { entidad: string; soloLectura?: boolean; compacto?: boolean; version?: number; acciones?: ReactNode }) {
  return <Pieza pieza="seguimiento.Actuaciones" {...props} />
}

/** Lo elegido en el directorio: una persona (con su institución) o una institución. */
export interface Eleccion {
  nombre: string
  cargo: string
  tratamiento: string
  ref:
    | { tipo: 'persona'; datos: { id: number; nombre: string; institucion_id: number | null } }
    | { tipo: 'institucion'; datos: { id: number; nombre: string } }
}

export interface PropsAutocompletado {
  etiqueta: ReactNode
  valor: string
  alEscribir: (v: string) => void
  alElegir: (e: Eleccion) => void
  alSalir?: () => void
  alPegar?: (texto: string) => boolean
  sx?: object
}

export const hayDirectorio = (): boolean => hayPieza('directorio.Autocompletado')

/** Sin el directorio (sola), el remitente se escribe como texto libre. */
export function AutocompletadoDirectorio(props: PropsAutocompletado) {
  const respaldo = (
    <TextField fullWidth size="small" label={props.etiqueta} value={props.valor} onChange={(e) => props.alEscribir(e.target.value)}
      onBlur={props.alSalir} sx={props.sx} />
  )
  return <Pieza pieza="directorio.Autocompletado" respaldo={respaldo} {...props} />
}
