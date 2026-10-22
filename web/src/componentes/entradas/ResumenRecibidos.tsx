/**
 * Tarjeta del INICIO (2026-10-06): lo recibido que espera — nuevas, por vencer,
 * vencidas y las mías — y las más urgentes. Sin nada abierto no se muestra.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import ButtonBase from '@mui/material/ButtonBase'
import Chip from '@mui/material/Chip'
import MoveToInboxOutlinedIcon from '@mui/icons-material/MoveToInboxOutlined'
import { PALETA, api } from '@qillqa/tiqsi'
import { hoyIso } from './apoyo'
import { atencionDe, textoPlazo, type ResumenEntradas } from './modelo'

export default function ResumenRecibidos() {
  const navegar = useNavigate()
  const [r, setR] = useState<ResumenEntradas | null>(null)
  useEffect(() => {
    api<ResumenEntradas>('/api/entradas/resumen').then(setR).catch(() => {})
  }, [])
  if (!r || r.nuevas + r.en_atencion === 0) return null
  const hoy = hoyIso()
  const cifras: { t: string; n: number; ruta: string; color?: string }[] = [
    { t: 'nuevas', n: r.nuevas, ruta: '/recibidos?estado=nueva' },
    { t: 'por vencer', n: r.por_vencer, ruta: '/recibidos?estado=abiertas', color: PALETA.avisoOscuro },
    { t: 'vencidas', n: r.vencidas, ruta: '/recibidos?vencidas=1', color: PALETA.error },
    { t: 'a mi cargo', n: r.mias, ruta: '/recibidos?responsable=yo' },
  ]
  return (
    <Box sx={{ mb: 3 }}>
      <Typography variant="subtitle2" component="h3" sx={{ mb: 1 }}>
        Mesa de Partes: por atender ({r.nuevas + r.en_atencion})
      </Typography>
      <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2.5, bgcolor: 'background.paper', overflow: 'hidden' }}>
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: 'repeat(2, 1fr)', sm: 'repeat(4, 1fr)' } }}>
          {cifras.map((c, i) => (
            <ButtonBase key={c.t} onClick={() => navegar(c.ruta)}
              sx={{ flexDirection: 'column', alignItems: 'flex-start', px: 2, py: 1.25, borderLeft: { xs: i % 2 ? '1px solid' : 'none', sm: i ? '1px solid' : 'none' }, borderTop: { xs: i > 1 ? '1px solid' : 'none', sm: 'none' }, borderColor: 'divider', '&:hover': { bgcolor: 'action.hover' } }}>
              <Typography sx={{ fontSize: 22, fontWeight: 650, lineHeight: 1.1, color: c.n && c.color ? c.color : 'text.primary' }}>{c.n}</Typography>
              <Typography variant="caption" color="text.secondary">{c.t}</Typography>
            </ButtonBase>
          ))}
        </Box>
        {r.urgentes.slice(0, 4).map((e) => (
          <ButtonBase key={e.id} onClick={() => navegar(`/recibidos?ver=${e.id}`)}
            sx={{ display: 'flex', width: '100%', justifyContent: 'flex-start', textAlign: 'left', gap: 1.5, px: 2, py: 1.1, borderTop: '1px solid', borderColor: 'divider', '&:hover': { bgcolor: 'action.hover' } }}>
            <MoveToInboxOutlinedIcon sx={{ color: 'primary.main', fontSize: 20 }} />
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Typography variant="body2" noWrap>{e.asunto || e.documento || 'Documento recibido'}</Typography>
              <Typography variant="caption" color="text.secondary" noWrap component="div">
                {[e.remitente, atencionDe(e.atencion), e.responsable].filter(Boolean).join(' · ')}
              </Typography>
            </Box>
            <Chip size="small" variant="outlined" label={textoPlazo(e.plazo, hoy)}
              sx={{ height: 22, fontSize: 12, flexShrink: 0, ...(e.vencida ? { color: PALETA.error, borderColor: PALETA.error } : e.por_vencer ? { color: PALETA.avisoOscuro, borderColor: PALETA.avisoBorde } : {}) }} />
          </ButtonBase>
        ))}
      </Box>
    </Box>
  )
}
