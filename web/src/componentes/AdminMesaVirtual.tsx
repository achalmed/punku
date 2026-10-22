/**
 * Administración de la MESA DE PARTES VIRTUAL (2026-10-12; backend/app/api/mesa_virtual.py): el enlace
 * público para compartir, el texto de presentación, el horario de atención y
 * los días no hábiles (para el cómputo de lo presentado fuera de hora y de los plazos), el plazo de
 * subsanación, los límites de tamaño y de envíos, y los tipos de documento que se ofrecen. Todo se
 * guarda en `ajustes` (clave `mesa_virtual`), nunca en el repositorio. Encenderla o apagarla, y el mensaje
 * que muestra apagada, van en Administración → Módulos (admin/Modulos.tsx, 2026-10-18): esto es su detalle.
 */
import { useEffect, useState } from 'react'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import FormControlLabel from '@mui/material/FormControlLabel'
import Switch from '@mui/material/Switch'
import TextField from '@mui/material/TextField'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import Typography from '@mui/material/Typography'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import { api } from '@qillqa/tiqsi'
import { copiarTexto, fechaHora } from './mesa/modelo'

interface Config {
  activa: boolean
  nombre: string
  receptor: string
  presentacion: string
  horario: { continua: boolean; inicio: string; fin: string; dias: number[] }
  no_habiles: string[]
  plazo_subsanacion: number
  max_archivo_mb: number
  max_total_mb: number
  max_anexos: number
  envios_por_hora: number
  envios_por_dia: number
  tipos: string[]
  enlace_publico: string
}

const DIAS_CORTOS = ['L', 'M', 'X', 'J', 'V', 'S', 'D']
const DIAS_LARGOS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']

export default function AdminMesaVirtual() {
  const [c, setC] = useState<Config | null>(null)
  const [guardada, setGuardada] = useState('')
  const [aviso, setAviso] = useState('')
  const [nuevoDia, setNuevoDia] = useState('')
  const [nuevoTipo, setNuevoTipo] = useState('')
  useEffect(() => {
    api<Config>('/api/mesa-virtual/config').then((r) => {
      setC(r)
      setGuardada(JSON.stringify(r))
    }).catch(() => undefined)
  }, [])
  if (!c) return null
  const enlace = c.enlace_publico || `${window.location.origin}/mesa-de-partes`
  const poner = (x: Partial<Config>) => setC({ ...c, ...x })
  const sucio = JSON.stringify(c) !== guardada
  const decir = (t: string) => {
    setAviso(t)
    window.setTimeout(() => setAviso(''), 3500)
  }
  const guardar = async (cambio?: Partial<Config>) => {
    try {
      const r = await api<Config>('/api/mesa-virtual/config', { method: 'PUT', body: JSON.stringify({ ...c, ...cambio }) })
      setC(r)
      setGuardada(JSON.stringify(r))
      decir('Guardado.')
    } catch (e) {
      decir(e instanceof Error ? e.message : 'No se pudo guardar.')
    }
  }
  const numero = (k: keyof Config, rotulo: string, ancho = 150) => (
    <TextField size="small" type="number" label={rotulo} value={c[k] as number} sx={{ width: ancho }}
      onChange={(e) => poner({ [k]: Number(e.target.value) } as Partial<Config>)} />
  )
  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Página pública, sin cuenta: se presenta un documento, se recibe el cargo y se sigue el trámite. Lo que llega aparece en Mesa de Partes.
      </Typography>

      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center', mb: 2 }}>
        <TextField size="small" label="Enlace público" value={c.enlace_publico} placeholder={enlace} sx={{ flex: '1 1 260px' }}
          onChange={(e) => poner({ enlace_publico: e.target.value })}
          helperText="El enlace permanente seguido de /mesa-de-partes. Vacío: el de esta pantalla." />
        <Button startIcon={<ContentCopyIcon />} onClick={() => void copiarTexto(enlace).then((ok) => decir(ok ? 'Enlace copiado.' : 'No se pudo copiar.'))}>Copiar enlace</Button>
        <Button startIcon={<OpenInNewIcon />} href={enlace} target="_blank" rel="noopener">Abrir</Button>
      </Box>

      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.75 }}>
        <TextField size="small" label="Nombre en el cargo" value={c.nombre} placeholder={c.receptor} onChange={(e) => poner({ nombre: e.target.value })}
          helperText="Vacío: el nombre del despacho de la configuración del sistema." />
        <TextField size="small" label="Presentación (breve)" multiline minRows={2} value={c.presentacion} onChange={(e) => poner({ presentacion: e.target.value })} inputProps={{ maxLength: 600 }} />

        <Box>
          <Typography variant="subtitle2" sx={{ mb: 0.25 }}>Horario de atención</Typography>
          <FormControlLabel
            control={<Switch checked={c.horario.continua} onChange={(e) => poner({ horario: { ...c.horario, continua: e.target.checked } })} />}
            label="Las 24 horas, todos los días"
          />
          {c.horario.continua ? (
            <Typography variant="caption" color="text.secondary" component="p">
              Lo que llega se tiene por presentado el día y la hora en que llegó (TUO de la Ley 27444, art. 117.1). Los plazos se cuentan en días hábiles, de lunes a viernes sin feriados.
            </Typography>
          ) : (<>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
            <ToggleButtonGroup size="small" value={c.horario.dias} onChange={(_, v: number[]) => v.length && poner({ horario: { ...c.horario, dias: v.sort() } })} aria-label="Días de atención">
              {DIAS_CORTOS.map((d, i) => <ToggleButton key={i} value={i} aria-label={DIAS_LARGOS[i]} sx={{ px: 1.25 }}>{d}</ToggleButton>)}
            </ToggleButtonGroup>
            <TextField size="small" type="time" label="Desde" value={c.horario.inicio} onChange={(e) => poner({ horario: { ...c.horario, inicio: e.target.value } })} sx={{ minWidth: 140 }} InputLabelProps={{ shrink: true }} />
            <TextField size="small" type="time" label="Hasta" value={c.horario.fin} onChange={(e) => poner({ horario: { ...c.horario, fin: e.target.value } })} sx={{ minWidth: 140 }} InputLabelProps={{ shrink: true }} />
          </Box>
          <Typography variant="caption" color="text.secondary">
            Se recibe a toda hora; lo que llega fuera de este horario o en un día no hábil se tiene por presentado el día hábil siguiente.
          </Typography>
          </>)}
        </Box>

        <Box>
          <Typography variant="subtitle2" sx={{ mb: 0.75 }}>Días no hábiles del despacho</Typography>
          <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', alignItems: 'center' }}>
            {c.no_habiles.map((d) => <Chip key={d} label={fechaHora(d)} onDelete={() => poner({ no_habiles: c.no_habiles.filter((x) => x !== d) })} size="small" />)}
            <TextField size="small" type="date" value={nuevoDia} onChange={(e) => setNuevoDia(e.target.value)} sx={{ width: 160 }} inputProps={{ 'aria-label': 'Día no hábil' }} />
            <Button size="small" disabled={!nuevoDia} onClick={() => { poner({ no_habiles: [...new Set([...c.no_habiles, nuevoDia])].sort() }); setNuevoDia('') }}>Agregar</Button>
          </Box>
          <Typography variant="caption" color="text.secondary">Los feriados nacionales y los días no laborables del sector público ya se cuentan solos.</Typography>
        </Box>

        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
          {numero('plazo_subsanacion', 'Días para subsanar', 160)}
          {numero('max_archivo_mb', 'MB por archivo')}
          {numero('max_total_mb', 'MB por envío')}
          {numero('max_anexos', 'Anexos como máximo', 170)}
          {numero('envios_por_hora', 'Envíos por hora (por conexión)', 230)}
          {numero('envios_por_dia', 'Envíos por día (por conexión)', 230)}
        </Box>

        <Box>
          <Typography variant="subtitle2" sx={{ mb: 0.75 }}>Tipos de documento que se ofrecen</Typography>
          <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', alignItems: 'center' }}>
            {c.tipos.map((t) => <Chip key={t} label={t} size="small" onDelete={c.tipos.length > 1 ? () => poner({ tipos: c.tipos.filter((x) => x !== t) }) : undefined} />)}
            <TextField size="small" value={nuevoTipo} onChange={(e) => setNuevoTipo(e.target.value)} placeholder="Otro tipo" sx={{ width: 160 }} inputProps={{ maxLength: 60, 'aria-label': 'Nuevo tipo de documento' }} />
            <Button size="small" disabled={!nuevoTipo.trim()} onClick={() => { poner({ tipos: [...new Set([...c.tipos, nuevoTipo.trim()])] }); setNuevoTipo('') }}>Agregar</Button>
          </Box>
        </Box>
      </Box>

      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mt: 2 }}>
        <Button variant="contained" onClick={() => void guardar()} disabled={!sucio}>Guardar</Button>
        {aviso && <Typography variant="caption" color="text.secondary">{aviso}</Typography>}
      </Box>
    </Box>
  )
}
