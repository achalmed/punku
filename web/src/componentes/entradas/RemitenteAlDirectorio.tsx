/**
 * EL REMITENTE AL DIRECTORIO (2026-10-13), dentro del trámite de la mesa de partes virtual. Edison:
 * «eso de datos personales podemos usarlo para el directorio, para tener contacto». El sistema
 * PROPONE la ficha (persona o institución, con su celular y correo) y dice si ya hay una igual
 * (mismo celular, correo o nombre; la entidad por RUC o nombre). Nada se crea solo: un toque en
 * «Vincular» o «Crear contacto» y el recibido queda vinculado a su ficha (docs/arquitectura.md §27).
 * backend/app/api/mesa_virtual.py, `GET|POST /entradas/{id}/contacto`.
 */
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Typography from '@mui/material/Typography'
import PersonOutlineIcon from '@mui/icons-material/PersonOutline'
import ApartmentOutlinedIcon from '@mui/icons-material/ApartmentOutlined'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import { PALETA, api } from '@qillqa/tiqsi'
import { rutaDe, telefonoLegible } from './apoyo'

interface Propuesta {
  propuesta: {
    persona: { nombre: string; cargo: string; celular: string; email: string } | null
    institucion: { nombre: string; ruc: string; email: string; telefono: string; direccion: string } | null
  }
  coincide: {
    persona: { id: number; nombre: string; cargo: string; motivo: string } | null
    institucion: { id: number; nombre: string; siglas: string; motivo: string } | null
  }
  vinculado: {
    persona: { id: number; nombre: string; cargo: string } | null
    institucion: { id: number; nombre: string; siglas: string } | null
  }
}

type Eleccion = { persona: string; persona_id?: number; institucion: string; institucion_id?: number }

export default function RemitenteAlDirectorio({ entradaId, soloLectura, alCambiar, alAvisar }: {
  entradaId: number
  soloLectura: boolean
  alCambiar: () => void
  alAvisar: (tipo: 'success' | 'error' | 'info', texto: string) => void
}) {
  const navegar = useNavigate()
  const [d, setD] = useState<Propuesta | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const cargar = useCallback(() => {
    api<Propuesta>(`/api/mesa-virtual/entradas/${entradaId}/contacto`).then(setD).catch(() => setD(null))
  }, [entradaId])
  useEffect(cargar, [cargar])
  if (!d) return null

  const llevar = async (e: Eleccion) => {
    setOcupado(true)
    try {
      const r = await api<Propuesta>(`/api/mesa-virtual/entradas/${entradaId}/contacto`, { method: 'POST', body: JSON.stringify(e) })
      setD(r)
      alAvisar('success', 'Listo: el remitente quedó en el directorio y vinculado a este documento.')
      alCambiar()
    } catch (x) {
      alAvisar('error', x instanceof Error ? x.message : 'No se pudo llevar al directorio.')
    } finally {
      setOcupado(false)
    }
  }

  const { propuesta: pr, coincide: co, vinculado: vi } = d
  const faltaPersona = Boolean(pr.persona && !vi.persona)
  const faltaInst = Boolean(pr.institucion && !vi.institucion)
  // A dónde lleva la ficha en el directorio, si el anfitrión lo tiene.
  const ver = (id: number) => { const r = rutaDe(`persona:${id}`); if (r) navegar(r) }
  const verInst = (id: number) => { const r = rutaDe(`inst:${id}`); if (r) navegar(r) }

  // Todo lo que corresponde ya está vinculado: una línea con el enlace a la ficha.
  if (!faltaPersona && !faltaInst) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', p: 1.25, border: '1px solid', borderColor: 'divider', borderRadius: 2, bgcolor: PALETA.superficieTenue }}>
        <CheckCircleOutlineIcon sx={{ color: PALETA.exito, fontSize: 20 }} />
        <Typography variant="body2" sx={{ flex: 1, minWidth: 0 }}>En el directorio:</Typography>
        {vi.persona && <Button size="small" onClick={() => ver(vi.persona!.id)}>{vi.persona.nombre}</Button>}
        {vi.institucion && <Button size="small" onClick={() => verInst(vi.institucion!.id)}>{vi.institucion.siglas || vi.institucion.nombre}</Button>}
      </Box>
    )
  }

  // Lo que se hará con un toque: vincular lo que coincide y crear lo que no está.
  const eleccion: Eleccion = {
    persona: faltaPersona ? (co.persona ? 'vincular' : 'crear') : 'omitir',
    persona_id: co.persona?.id,
    institucion: faltaInst ? (co.institucion ? 'vincular' : 'crear') : 'omitir',
    institucion_id: co.institucion?.id,
  }
  const contacto = (c: { celular?: string; telefono?: string; email: string }) =>
    [c.celular ? telefonoLegible(c.celular) : c.telefono ? telefonoLegible(c.telefono) : '', c.email].filter(Boolean).join(' · ')

  return (
    <Box sx={{ p: 1.5, border: '1px solid', borderColor: PALETA.avisoBorde, borderRadius: 2, bgcolor: PALETA.avisoFondo }}>
      <Typography variant="subtitle2" sx={{ mb: 0.75 }}>¿Guardar al remitente en el directorio?</Typography>
      {faltaInst && pr.institucion && (
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-start', mb: 0.75 }}>
          <ApartmentOutlinedIcon sx={{ fontSize: 20, color: 'text.secondary', mt: 0.25 }} />
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>{pr.institucion.nombre}</Typography>
            <Typography variant="caption" color="text.secondary" component="div">
              {[pr.institucion.ruc && `RUC ${pr.institucion.ruc}`, contacto(pr.institucion)].filter(Boolean).join(' · ')}
            </Typography>
            <Typography variant="caption" component="div" sx={{ color: co.institucion ? PALETA.avisoOscuro : 'text.secondary' }}>
              {co.institucion ? `Ya está: ${co.institucion.siglas || co.institucion.nombre} (${co.institucion.motivo}) → se vincula` : 'No está → se crea'}
            </Typography>
          </Box>
        </Box>
      )}
      {faltaPersona && pr.persona && (
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'flex-start', mb: 0.75 }}>
          <PersonOutlineIcon sx={{ fontSize: 20, color: 'text.secondary', mt: 0.25 }} />
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>{pr.persona.nombre}{pr.persona.cargo ? ` · ${pr.persona.cargo}` : ''}</Typography>
            <Typography variant="caption" color="text.secondary" component="div">{contacto(pr.persona) || 'Sin celular ni correo'}</Typography>
            <Typography variant="caption" component="div" sx={{ color: co.persona ? PALETA.avisoOscuro : 'text.secondary' }}>
              {co.persona ? `Ya está: ${co.persona.nombre} (${co.persona.motivo}) → se vincula y se completa lo que le falte` : 'No está → se crea el contacto'}
            </Typography>
          </Box>
        </Box>
      )}
      {!soloLectura && (
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1 }}>
          <Button size="small" variant="contained" disableElevation disabled={ocupado} onClick={() => void llevar(eleccion)}>
            {(eleccion.persona === 'vincular' || eleccion.institucion === 'vincular') && eleccion.persona !== 'crear' && eleccion.institucion !== 'crear'
              ? 'Vincular' : eleccion.persona === 'vincular' || eleccion.institucion === 'vincular' ? 'Vincular y crear' : 'Crear contacto'}
          </Button>
          {/* Si lo que coincide no es la misma persona: crear una ficha aparte. */}
          {co.persona && faltaPersona && (
            <Button size="small" disabled={ocupado} onClick={() => void llevar({ ...eleccion, persona: 'crear', persona_id: undefined })}>No es la misma: crear otro</Button>
          )}
        </Box>
      )}
      <Typography variant="caption" color="text.secondary" component="p" sx={{ mt: 0.75 }}>
        Con su autorización (Ley 29733): para atender el trámite y mantener contacto. El documento de identidad no pasa al directorio.
      </Typography>
    </Box>
  )
}
