/**
 * La propuesta «Crear también en la Agenda» que acompaña a un recibido que convoca a una
 * actividad (2026-10-06; desde el 2026-10-11 la trae el pegado). Si el evento ya está en
 * la Agenda, se vincula en vez de crearlo otra vez. La usan la subida y el detalle.
 */
import Box from '@mui/material/Box'
import Checkbox from '@mui/material/Checkbox'
import Typography from '@mui/material/Typography'
import { PALETA } from '@qillqa/tiqsi'
import { fechaCorta, type EventoPropuesto } from './modelo'

/** «jue 03/09 18:30» (sin hora si es de todo el día). */
export const cuandoDe = (ev: Pick<EventoPropuesto, 'inicio' | 'todo_el_dia'>) => {
  const d = new Date(`${ev.inicio.slice(0, 10)}T12:00:00`)
  const dia = d.toLocaleDateString('es-PE', { weekday: 'short' }).replace('.', '')
  return `${dia} ${fechaCorta(ev.inicio).slice(0, 5)}${ev.todo_el_dia ? '' : ` ${ev.inicio.slice(11, 16)}`}`
}

export default function PropuestaEvento({ evento, existente, marcado, alMarcar }: {
  evento: EventoPropuesto
  existente: { id: number; titulo: string; inicio: string } | null | undefined
  marcado: boolean
  alMarcar: (v: boolean) => void
}) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, p: 0.75, borderRadius: 1.5, border: '1px solid', borderColor: 'divider', bgcolor: PALETA.superficieTenue }}>
      <Checkbox size="small" checked={marcado} onChange={(e) => alMarcar(e.target.checked)} inputProps={{ 'aria-label': existente ? 'Vincular al evento de la Agenda' : 'Llevar a la Agenda, por confirmar' }} />
      <Box sx={{ minWidth: 0 }}>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          {/* 2026-10-18: lo que pide un recibido es una solicitud; entra «Por confirmar», fuera del calendario. */}
          {existente ? 'Vincular al evento que ya está en la Agenda' : 'Llevar a la Agenda, por confirmar'}
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', wordBreak: 'break-word' }}>
          {existente
            ? [cuandoDe({ ...evento, inicio: existente.inicio }), existente.titulo].join(' · ')
            : [cuandoDe(evento), evento.titulo, evento.lugar].filter(Boolean).join(' · ')}
        </Typography>
      </Box>
    </Box>
  )
}
