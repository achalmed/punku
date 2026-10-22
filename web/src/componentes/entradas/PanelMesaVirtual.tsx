/**
 * MESA DE PARTES VIRTUAL dentro de Mesa de Partes (antes Recibidos; 2026-10-12; backend/app/api/mesa_virtual.py): lo que
 * llegó por la página pública. Expediente y código (para dictarlos por teléfono), el remitente con
 * su contacto, los archivos con su huella, la historia y el estado que VE el remitente, con las
 * acciones que lo cambian: En revisión, Observar (qué subsanar y plazo en días hábiles), Derivar,
 * Atender (con la respuesta: un documento propio de Qillqa o un PDF) y Archivar.
 *
 * Todo lo demás del recibido (responder, agendar, crear tarea, pegar el resultado del prompt,
 * vincular) sigue en sus pestañas de siempre: aquí solo lo que la mesa añade.
 */
import { useCallback, useEffect, useState } from 'react'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import IconButton from '@mui/material/IconButton'
import LinearProgress from '@mui/material/LinearProgress'
import MenuItem from '@mui/material/MenuItem'
import TextField from '@mui/material/TextField'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import Alert from '@mui/material/Alert'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import DownloadIcon from '@mui/icons-material/Download'
import { PALETA, api, descargarArchivo, subirArchivo } from '@qillqa/tiqsi'
import { CLASE_ARCHIVO, copiarTexto, fechaHora, peso, presentadoOtroDia, type EstadoPublico, type TramiteInterno } from '../mesa/modelo'
import type { DocBreve } from './modelo'
import RemitenteAlDirectorio from './RemitenteAlDirectorio'

const COLOR: Record<EstadoPublico, string> = {
  recibido: PALETA.guinda,
  en_revision: PALETA.info,
  observado: PALETA.aviso,
  derivado: PALETA.aprobado,
  atendido: PALETA.exito,
  archivado: PALETA.archivado,
}

type Accion = 'revision' | 'observar' | 'derivar' | 'archivar' | 'reabrir' | 'atender'

const TITULO: Record<Accion, string> = {
  revision: 'Poner en revisión',
  observar: 'Observar: pedir que subsane',
  derivar: 'Derivar / En atención',
  archivar: 'Archivar el trámite',
  reabrir: 'Reabrir el trámite',
  atender: 'Atender con la respuesta',
}

function FilaCopiar({ rotulo, valor, alAvisar }: { rotulo: string; valor: string; alAvisar: (t: 'success' | 'error' | 'info', x: string) => void }) {
  if (!valor) return null
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 0.25 }}>
      <Typography variant="caption" color="text.secondary" sx={{ width: 104, flexShrink: 0 }}>{rotulo}</Typography>
      <Typography variant="body2" sx={{ flex: 1, minWidth: 0, wordBreak: 'break-word' }}>{valor}</Typography>
      <Tooltip title={`Copiar ${rotulo.toLowerCase()}`}>
        <IconButton size="small" aria-label={`Copiar ${rotulo.toLowerCase()}`}
          onClick={() => void copiarTexto(valor).then((ok) => alAvisar(ok ? 'info' : 'error', ok ? `${rotulo} copiado.` : 'No se pudo copiar.'))}>
          <ContentCopyIcon sx={{ fontSize: 16 }} />
        </IconButton>
      </Tooltip>
    </Box>
  )
}

export default function PanelMesaVirtual({
  entradaId,
  soloLectura,
  respuesta,
  vinculos,
  alCambiar,
  alAvisar,
}: {
  entradaId: number
  soloLectura: boolean
  respuesta: DocBreve | null
  vinculos: DocBreve[]
  alCambiar: () => void
  alAvisar: (tipo: 'success' | 'error' | 'info', texto: string) => void
}) {
  const [t, setT] = useState<TramiteInterno | null>(null)
  const [accion, setAccion] = useState<Accion | null>(null)
  const [nota, setNota] = useState('')
  const [dias, setDias] = useState(2)
  const [plazo, setPlazo] = useState('')
  const [docId, setDocId] = useState<number | ''>('')
  const [archivo, setArchivo] = useState<File | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const [error, setError] = useState('')

  const cargar = useCallback(async () => {
    try {
      const v = await api<TramiteInterno>(`/api/mesa-virtual/entradas/${entradaId}`)
      setT(v)
      setDias(v.dias_subsanacion)
    } catch (e) {
      alAvisar('error', e instanceof Error ? e.message : 'No se pudo abrir el trámite de la mesa virtual.')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entradaId])
  useEffect(() => {
    void cargar()
  }, [cargar])
  // El plazo que saldría con N días hábiles (desde el día hábil siguiente).
  useEffect(() => {
    if (accion !== 'observar') return
    api<{ plazo: string; hasta: string }>(`/api/mesa-virtual/plazo?dias=${dias}`).then((r) => setPlazo(r.plazo)).catch(() => setPlazo(''))
  }, [accion, dias])

  const abrir = (a: Accion) => {
    setAccion(a)
    setNota('')
    setError('')
    setArchivo(null)
    const candidatos = [respuesta, ...vinculos].filter(Boolean) as DocBreve[]
    setDocId(a === 'atender' && candidatos.length ? candidatos[0].id : '')
  }

  const confirmar = async () => {
    if (!accion) return
    setOcupado(true)
    setError('')
    try {
      let v: TramiteInterno
      if (accion === 'atender') {
        const f = new FormData()
        f.append('nota', nota.trim())
        if (archivo) f.append('archivo', archivo)
        else if (docId) f.append('documento_id', String(docId))
        else throw new Error('Elija el documento que responde o suba el PDF.')
        v = await subirArchivo<TramiteInterno>(`/api/mesa-virtual/entradas/${entradaId}/atender`, f)
      } else {
        v = await api<TramiteInterno>(`/api/mesa-virtual/entradas/${entradaId}/accion`, {
          method: 'POST', body: JSON.stringify({ accion, nota: nota.trim(), dias: accion === 'observar' ? dias : null }),
        })
      }
      setT(v)
      setAccion(null)
      alAvisar('success', accion === 'observar' ? `Observado: el remitente lo verá en su seguimiento, con plazo hasta el ${fechaHora(v.observacion?.plazo)}.`
        : accion === 'atender' ? 'Atendido: el remitente ya puede descargar la respuesta.' : `Estado: ${v.estado_texto}.`)
      alCambiar()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo completar.')
    } finally {
      setOcupado(false)
    }
  }

  if (!t) return <LinearProgress />
  const cerrado = t.estado === 'atendido' || t.estado === 'archivado'
  const r = t.remitente
  const candidatos = [respuesta, ...vinculos.filter((x) => x.id !== respuesta?.id)].filter(Boolean) as DocBreve[]

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
          <Chip size="small" label={`Lo que ve el remitente: ${t.estado_texto}`} sx={{ bgcolor: `${COLOR[t.estado]}1A`, color: COLOR[t.estado], fontWeight: 600 }} />
          {t.fuera_de_horario && <Chip size="small" variant="outlined" label="Llegó fuera de horario" />}
        </Box>
        <Box sx={{ mt: 1 }}>
          <FilaCopiar rotulo="Expediente" valor={t.expediente} alAvisar={alAvisar} />
          <FilaCopiar rotulo="Código" valor={t.codigo} alAvisar={alAvisar} />
          <Typography variant="caption" color="text.secondary">
            Recibido el {fechaHora(t.recibido_en)}{presentadoOtroDia(t) ? ` · se tiene por presentado el ${fechaHora(t.presentado_el)}` : ''}
          </Typography>
        </Box>
      </Box>

      {t.observacion && (
        <Alert severity={t.observacion.vencido ? 'error' : 'warning'} variant="outlined">
          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{t.observacion.texto}</Typography>
          <Typography variant="caption">
            {t.observacion.vencido ? `Venció el ${fechaHora(t.observacion.plazo)} sin subsanar: puede archivarlo como no presentado (TUO 27444, art. 125.4).`
              : `Plazo para subsanar: hasta el ${fechaHora(t.observacion.plazo)} (${t.observacion.hasta}).`}
          </Typography>
        </Alert>
      )}

      {!soloLectura && (
        <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap' }}>
          {!cerrado && (
            <>
              <Button size="small" variant="contained" onClick={() => abrir('atender')}>Atender</Button>
              {t.estado !== 'observado' && <Button size="small" variant="outlined" onClick={() => abrir('observar')}>Observar</Button>}
              {t.estado === 'recibido' && <Button size="small" variant="outlined" onClick={() => abrir('revision')}>En revisión</Button>}
              {t.estado !== 'derivado' && <Button size="small" variant="outlined" onClick={() => abrir('derivar')}>Derivar</Button>}
              <Button size="small" color="inherit" onClick={() => abrir('archivar')}>Archivar</Button>
            </>
          )}
          {cerrado && <Button size="small" variant="outlined" onClick={() => abrir('reabrir')}>Reabrir</Button>}
        </Box>
      )}

      <Box>
        <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Remitente</Typography>
        <FilaCopiar rotulo={r.tipo_persona === 'juridica' ? 'Entidad' : 'Nombre'} valor={r.nombre} alAvisar={alAvisar} />
        <FilaCopiar rotulo={r.doc_tipo} valor={r.doc} alAvisar={alAvisar} />
        {r.representante && <FilaCopiar rotulo="Representante" valor={`${r.representante}${r.cargo ? ` (${r.cargo})` : ''}`} alAvisar={alAvisar} />}
        {r.representante_doc && <FilaCopiar rotulo={r.representante_doc_tipo || 'DNI'} valor={r.representante_doc} alAvisar={alAvisar} />}
        <FilaCopiar rotulo="Celular" valor={r.telefono ?? ''} alAvisar={alAvisar} />
        <FilaCopiar rotulo="Correo" valor={r.correo ?? ''} alAvisar={alAvisar} />
        <FilaCopiar rotulo="Dirección" valor={r.direccion ?? ''} alAvisar={alAvisar} />
      </Box>

      {/* El remitente al directorio (2026-10-13): se propone; se confirma con un toque. */}
      <RemitenteAlDirectorio entradaId={entradaId} soloLectura={soloLectura} alCambiar={() => { void cargar(); alCambiar() }} alAvisar={alAvisar} />

      <Box>
        <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Documento</Typography>
        <Typography variant="body2">{[t.documento.tipo, t.documento.numero].filter(Boolean).join(' ')} · {t.documento.folios} folio(s)</Typography>
        {t.documento.referencia && <Typography variant="body2" color="text.secondary">Referencia: {t.documento.referencia}</Typography>}
        {t.documento.comentario && <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap' }}>{t.documento.comentario}</Typography>}
      </Box>

      <Box>
        <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Archivos</Typography>
        {t.archivos.map((a) => (
          <Box key={a.id} sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 0.5, borderBottom: '1px solid', borderColor: 'divider' }}>
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Typography variant="body2" noWrap title={a.nombre}>
                {CLASE_ARCHIVO[a.clase]}: {a.nombre}
              </Typography>
              <Typography variant="caption" color={a.fuera_de_plazo ? 'error' : 'text.secondary'}>
                {peso(a.bytes)}{a.tipo === 'pdf' && a.paginas ? ` · ${a.paginas} pág.` : ''} · {fechaHora(a.fecha)}{a.fuera_de_plazo ? ' · fuera de plazo' : ''}
              </Typography>
            </Box>
            <Tooltip title="Descargar">
              <IconButton size="small" aria-label={`Descargar ${a.nombre}`} onClick={() => void descargarArchivo(`/api/mesa-virtual/archivos/${a.id}`).catch((e) => alAvisar('error', e instanceof Error ? e.message : 'No se pudo descargar.'))}>
                <DownloadIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
        ))}
      </Box>

      <Box>
        <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Historia</Typography>
        {[...t.historia].reverse().map((h, i) => (
          <Box key={`${h.fecha}-${i}`} sx={{ py: 0.6, borderBottom: '1px solid', borderColor: 'divider' }}>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>
              {h.texto} <Typography component="span" variant="caption" color="text.secondary">· {fechaHora(h.fecha)}{h.usuario ? ` · ${h.usuario}` : ' · el remitente'}</Typography>
            </Typography>
            {h.nota && <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap' }}>{h.nota}</Typography>}
          </Box>
        ))}
      </Box>
      {t.declaracion?.en && (
        <Typography variant="caption" color="text.secondary">Declaración jurada y autorización de datos personales aceptadas el {fechaHora(t.declaracion.en)}.</Typography>
      )}

      <Dialog open={accion !== null} onClose={() => !ocupado && setAccion(null)} fullWidth maxWidth="sm">
        <DialogTitle>{accion ? TITULO[accion] : ''}</DialogTitle>
        <DialogContent sx={{ display: 'flex', flexDirection: 'column', gap: 1.5, pt: '8px !important' }}>
          {accion === 'observar' && (
            <>
              <TextField label="Qué falta o qué debe corregir" multiline minRows={3} value={nota} onChange={(e) => setNota(e.target.value)} autoFocus
                helperText="Lo lee el remitente. Todo en un solo acto: no se puede volver a observar por otra cosa (TUO 27444, art. 126.2)." />
              <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
                <TextField select size="small" label="Plazo" value={dias} onChange={(e) => setDias(Number(e.target.value))} sx={{ width: 170 }}>
                  {[1, 2, 3, 4, 5, 7, 10].map((n) => <MenuItem key={n} value={n}>{n} día{n > 1 ? 's' : ''} hábil{n > 1 ? 'es' : ''}</MenuItem>)}
                </TextField>
                {plazo && <Typography variant="body2" color="text.secondary">Hasta el {fechaHora(plazo)}</Typography>}
              </Box>
            </>
          )}
          {accion === 'atender' && (
            <>
              {candidatos.length > 0 && (
                <TextField select label="Documento propio que responde" value={archivo ? '' : docId} onChange={(e) => { setDocId(Number(e.target.value)); setArchivo(null); setError('') }}
                  helperText="Se entrega el firmado si lo tiene; si no, el PDF generado. Queda vinculado como respuesta del recibido.">
                  {candidatos.map((c) => <MenuItem key={c.id} value={c.id}>{c.numero} · {c.estado.toLowerCase()} · {c.asunto.slice(0, 60)}</MenuItem>)}
                </TextField>
              )}
              <Box>
                <Button component="label" variant="outlined" size="small">
                  {archivo ? `PDF: ${archivo.name}` : candidatos.length ? 'O subir un PDF' : 'Subir el PDF de la respuesta'}
                  <input hidden type="file" accept="application/pdf,.pdf" onChange={(e) => { setArchivo(e.target.files?.[0] ?? null); e.target.value = ''; setError('') }} />
                </Button>
                {!candidatos.length && (
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                    Para entregar un oficio del sistema, vincúlelo antes en «Respuestas y relaciones» o créelo con «Responder».
                  </Typography>
                )}
              </Box>
              <TextField label="Mensaje para el remitente (opcional)" multiline minRows={2} value={nota} onChange={(e) => setNota(e.target.value)} />
            </>
          )}
          {(accion === 'derivar' || accion === 'archivar' || accion === 'revision' || accion === 'reabrir') && (
            <TextField label={accion === 'archivar' ? 'Motivo (lo lee el remitente)' : 'Nota para el remitente (opcional)'} multiline minRows={2} value={nota}
              onChange={(e) => setNota(e.target.value)} autoFocus
              placeholder={accion === 'archivar' ? 'Por ejemplo: no se subsanó dentro del plazo; se tiene por no presentado.' : ''} />
          )}
          {error && <Alert severity="error">{error}</Alert>}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAccion(null)} disabled={ocupado}>Cancelar</Button>
          <Button variant="contained" onClick={() => void confirmar()} disabled={ocupado || (accion === 'observar' && nota.trim().length < 10)}>
            {accion ? (accion === 'observar' ? 'Observar' : accion === 'atender' ? 'Atender' : 'Confirmar') : ''}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

