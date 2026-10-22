/**
 * «Seguir mi trámite» (mesa de partes virtual, 2026-10-12): con el código de seguimiento y el
 * documento de identidad de quien envió (o de quien representa), el estado en una línea de tiempo,
 * la observación con su plazo y el botón para subsanar, la respuesta para descargar y el cargo.
 * Nada se guarda en el navegador: al recargar se vuelve a pedir el código y el documento.
 */
import { useState } from 'react'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import Alert from '@mui/material/Alert'
import Chip from '@mui/material/Chip'
import LinearProgress from '@mui/material/LinearProgress'
import SearchIcon from '@mui/icons-material/Search'
import DownloadIcon from '@mui/icons-material/Download'
import UploadFileIcon from '@mui/icons-material/UploadFile'
import CheckIcon from '@mui/icons-material/Check'
import { PALETA } from '@qillqa/tiqsi'
import ElegirArchivos, { PDF_O_IMAGEN, motivoArchivo } from './ElegirArchivos'
import { Fila } from './Cargo'
import {
  CAMINO, CLASE_ARCHIVO, ETIQUETA, descargar, enviarConAvance, fechaHora, peso, presentadoOtroDia, seguir,
  type EstadoPublico, type RespuestaTramite, type Tramite,
} from './modelo'

const COLOR: Record<EstadoPublico, string> = {
  recibido: PALETA.guinda,
  en_revision: PALETA.info,
  observado: PALETA.aviso,
  derivado: PALETA.aprobado,
  atendido: PALETA.exito,
  archivado: PALETA.archivado,
}

/** Línea de tiempo: el camino habitual, con lo hecho, lo actual y lo que falta. */
function LineaTiempo({ t }: { t: Tramite }) {
  const fuera = t.estado === 'observado' || t.estado === 'archivado'
  const actual = fuera ? (t.estado === 'observado' ? 1 : CAMINO.length) : CAMINO.indexOf(t.estado)
  const fechaDe = (e: EstadoPublico) => [...t.historia].reverse().find((h) => h.estado === e)?.fecha ?? ''
  return (
    <Box component="ol" aria-label="Estado del trámite" sx={{ listStyle: 'none', p: 0, m: 0, position: 'relative' }}>
      {CAMINO.map((e, i) => {
        const hecho = i < actual || (i === actual && e === 'atendido')
        const ahora = i === actual && !fuera && e !== 'atendido'
        const observadoAqui = t.estado === 'observado' && i === 1
        const color = observadoAqui ? PALETA.aviso : hecho || ahora ? COLOR[e] : PALETA.apagado
        return (
          <Box component="li" key={e} sx={{ display: 'flex', gap: 1.25, pb: i < CAMINO.length - 1 ? 1.5 : 0, position: 'relative' }}>
            {i < CAMINO.length - 1 && <Box sx={{ position: 'absolute', left: 11, top: 24, bottom: 0, width: 2, bgcolor: i < actual ? color : PALETA.borde }} />}
            <Box sx={{ width: 24, height: 24, borderRadius: '50%', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center',
              // Hecho: velo del tono con la marca del mismo tono (2026-10-19: nada de relleno con blanco, que en la oscura no se lee).
              border: '2px solid', borderColor: color, bgcolor: hecho ? `${color}26` : ahora || observadoAqui ? 'background.paper' : 'transparent', color }}>
              {hecho && <CheckIcon sx={{ fontSize: 15 }} />}
              {(ahora || observadoAqui) && <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: color }} />}
            </Box>
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="body2" sx={{ fontWeight: ahora || observadoAqui ? 700 : 600, color: hecho || ahora || observadoAqui ? 'text.primary' : 'text.secondary' }}>
                {observadoAqui ? 'Observado: falta subsanar' : ETIQUETA[e]}
              </Typography>
              {(hecho || ahora) && fechaDe(e) && <Typography variant="caption" color="text.secondary">{fechaHora(fechaDe(e))}</Typography>}
            </Box>
          </Box>
        )
      })}
      {t.estado === 'archivado' && (
        <Typography variant="body2" sx={{ mt: 1.5, fontWeight: 600, color: PALETA.archivado }}>Archivado el {fechaHora(fechaDe('archivado'))}</Typography>
      )}
    </Box>
  )
}

function Subsanar({ t, acceso, alListo }: { t: Tramite; acceso: string; alListo: (r: RespuestaTramite) => void }) {
  const [archivos, setArchivos] = useState<File[]>([])
  const [nota, setNota] = useState('')
  const [error, setError] = useState('')
  const [avance, setAvance] = useState<number | null>(null)
  const enviar = async () => {
    const malo = archivos.find((f) => motivoArchivo(f, PDF_O_IMAGEN, t.max_archivo_mb))
    if (!archivos.length) return setError('Adjunte al menos un archivo.')
    if (malo) return setError(`«${malo.name}» ${motivoArchivo(malo, PDF_O_IMAGEN, t.max_archivo_mb)}.`)
    setError('')
    const f = new FormData()
    f.append('acceso', acceso)
    f.append('nota', nota.trim())
    archivos.forEach((a) => f.append('archivos', a))
    setAvance(0)
    try {
      alListo(await enviarConAvance('/subsanar', f, setAvance))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo enviar la subsanación.')
    } finally {
      setAvance(null)
    }
  }
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25, mt: 1.5 }}>
      <ElegirArchivos id="subsanacion" etiqueta="Adjuntar lo que subsana" archivos={archivos} alCambiar={(a) => { setArchivos(a); setError('') }}
        multiple maximo={6} admitidos={PDF_O_IMAGEN} maxMb={t.max_archivo_mb} />
      <TextField label="Nota (opcional)" multiline minRows={2} value={nota} onChange={(e) => setNota(e.target.value)} inputProps={{ maxLength: 2000 }} fullWidth />
      {error && <Alert severity="error" role="alert">{error}</Alert>}
      {avance !== null && <LinearProgress variant={avance < 1 ? 'determinate' : 'indeterminate'} value={avance * 100} />}
      <Button variant="contained" startIcon={<UploadFileIcon />} onClick={() => void enviar()} disabled={avance !== null} sx={{ alignSelf: { xs: 'stretch', sm: 'flex-start' }, py: 1.1 }}>
        Enviar la subsanación
      </Button>
    </Box>
  )
}

export function VistaTramite({ r, alCambiar }: { r: RespuestaTramite; alCambiar: (r: RespuestaTramite) => void }) {
  const t = r.tramite
  const [error, setError] = useState('')
  const [hecho, setHecho] = useState('')
  const bajar = async (ruta: '/cargo' | '/respuesta', nombre: string, id?: number) => {
    setError('')
    try {
      await descargar(ruta, r.acceso, nombre, id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudo descargar.')
    }
  }
  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Box>
        <Typography variant="caption" color="text.secondary">Expediente {t.expediente} · código {t.codigo}</Typography>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
          <Typography component="h2" sx={{ fontWeight: 700, fontSize: 18 }}>{t.documento.asunto}</Typography>
        </Box>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.5, flexWrap: 'wrap' }}>
          <Chip label={t.estado_texto} sx={{ bgcolor: `${COLOR[t.estado]}1A`, color: COLOR[t.estado], fontWeight: 600 }} />
          <Typography variant="body2" color="text.secondary">{t.explicacion}</Typography>
        </Box>
      </Box>
      {hecho && <Alert severity="success" onClose={() => setHecho('')}>{hecho}</Alert>}

      {/* 2026-10-19: tarjeta clara con un punto arena, no una caja amarilla ni un título de color. */}
      {t.observacion && (
        <Box sx={{ border: '1px solid', borderColor: 'divider', bgcolor: 'background.paper', borderRadius: 1.5, p: 1.75 }}>
          <Typography sx={{ fontWeight: 700, display: 'flex', alignItems: 'center', gap: 1 }}>
            <Box component="span" sx={{ width: 7, height: 7, borderRadius: '50%', bgcolor: PALETA.aviso, flexShrink: 0 }} />
            Qué debe subsanar
          </Typography>
          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', my: 0.75 }}>{t.observacion.texto}</Typography>
          <Typography variant="body2" sx={{ fontWeight: 600, color: t.observacion.vencido ? PALETA.error : PALETA.avisoOscuro }}>
            {t.observacion.vencido
              ? `El plazo venció el ${fechaHora(t.observacion.plazo)}. Puede enviar igual: el despacho decidirá.`
              : `Plazo: hasta el ${fechaHora(t.observacion.plazo)}, a las ${t.observacion.hasta}.`}
          </Typography>
          {t.puede_subsanar && (
            <Subsanar t={t} acceso={r.acceso} alListo={(n) => { alCambiar(n); setHecho('Subsanación recibida. Descargue de nuevo su cargo: ahora incluye los archivos nuevos.') }} />
          )}
        </Box>
      )}

      {t.respuestas.length > 0 && (
        <Box sx={{ border: '1px solid', borderColor: 'divider', bgcolor: 'background.paper', borderRadius: 1.5, p: 1.75 }}>
          <Typography sx={{ fontWeight: 700, mb: 0.75, display: 'flex', alignItems: 'center', gap: 1 }}>
            <Box component="span" sx={{ width: 7, height: 7, borderRadius: '50%', bgcolor: PALETA.exito, flexShrink: 0 }} />
            Respuesta del despacho
          </Typography>
          {t.historia.filter((h) => h.accion === 'atendido' && h.nota).slice(-1).map((h) => (
            <Typography key={h.fecha} variant="body2" sx={{ mb: 1, whiteSpace: 'pre-wrap' }}>{h.nota}</Typography>
          ))}
          {t.respuestas.map((a) => (
            <Button key={a.id} variant="contained" startIcon={<DownloadIcon />} onClick={() => void bajar('/respuesta', `Respuesta-${t.expediente}.${a.tipo}`, a.id)}
              sx={{ mr: 1, mb: 0.5 }}>
              Descargar la respuesta ({peso(a.bytes)})
            </Button>
          ))}
        </Box>
      )}

      <Box>
        <Typography variant="subtitle2" sx={{ mb: 1 }}>Estado</Typography>
        <LineaTiempo t={t} />
      </Box>

      <Box>
        <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Historia</Typography>
        {[...t.historia].reverse().map((h, i) => (
          <Box key={`${h.fecha}-${i}`} sx={{ py: 0.75, borderBottom: '1px solid', borderColor: 'divider' }}>
            <Typography variant="body2" sx={{ fontWeight: 600 }}>{h.texto} <Typography component="span" variant="caption" color="text.secondary">· {fechaHora(h.fecha)}</Typography></Typography>
            {h.nota && <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'pre-wrap' }}>{h.nota}</Typography>}
          </Box>
        ))}
      </Box>

      <Box>
        <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Lo que presentó</Typography>
        <Fila rotulo="Remitente">{t.remitente.nombre} · {t.remitente.doc_tipo} {t.remitente.doc}</Fila>
        <Fila rotulo="Documento">{[t.documento.tipo, t.documento.numero].filter(Boolean).join(' ')} · {t.documento.folios} folio(s)</Fila>
        <Fila rotulo="Recibido">{fechaHora(t.recibido_en)}{presentadoOtroDia(t) ? ` · se tiene por presentado el ${fechaHora(t.presentado_el)}` : ''}</Fila>
        <Fila rotulo="Archivos">
          {t.archivos.map((a) => (
            <Box key={a.id}>{CLASE_ARCHIVO[a.clase]}: {a.nombre} ({peso(a.bytes)}){a.fuera_de_plazo ? ' · fuera de plazo' : ''}</Box>
          ))}
        </Fila>
      </Box>
      {error && <Alert severity="error" role="alert">{error}</Alert>}
      <Button variant="outlined" startIcon={<DownloadIcon />} onClick={() => void bajar('/cargo', `Cargo-${t.expediente}.pdf`)} sx={{ alignSelf: { xs: 'stretch', sm: 'flex-start' } }}>
        Descargar mi cargo (PDF)
      </Button>
    </Box>
  )
}

export default function Seguimiento({ inicial, codigoInicial = '' }: { inicial: RespuestaTramite | null; codigoInicial?: string }) {
  const [r, setR] = useState<RespuestaTramite | null>(inicial)
  const [codigo, setCodigo] = useState(codigoInicial)
  const [documento, setDocumento] = useState('')
  const [error, setError] = useState('')
  const [buscando, setBuscando] = useState(false)
  const buscar = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!codigo.trim() || !documento.trim()) return setError('Escriba el código y su número de documento.')
    setError('')
    setBuscando(true)
    try {
      setR(await seguir(codigo, documento))
      window.scrollTo(0, 0)
    } catch (x) {
      setError(x instanceof Error ? x.message : 'No se pudo consultar.')
    } finally {
      setBuscando(false)
    }
  }
  if (r) {
    return (
      <Box>
        <VistaTramite r={r} alCambiar={setR} />
        <Button sx={{ mt: 2 }} onClick={() => { setR(null); setDocumento('') }}>Consultar otro trámite</Button>
      </Box>
    )
  }
  return (
    <Box component="form" onSubmit={buscar} noValidate sx={{ display: 'flex', flexDirection: 'column', gap: 1.75 }}>
      <Typography component="h2" sx={{ fontWeight: 700, fontSize: 18 }}>Seguir mi trámite</Typography>
      <Typography variant="body2" color="text.secondary">El código está en su cargo (por ejemplo, K7QF-9M2X-HT4P).</Typography>
      <TextField label="Código de seguimiento" value={codigo} onChange={(e) => setCodigo(e.target.value.toUpperCase())} required fullWidth
        inputProps={{ autoCapitalize: 'characters', autoComplete: 'off', spellCheck: false, maxLength: 20, style: { fontFamily: 'ui-monospace, Consolas, monospace', letterSpacing: '0.06em' } }} />
      <TextField label="Su DNI, carné de extranjería o RUC" value={documento} onChange={(e) => setDocumento(e.target.value)} required fullWidth
        helperText="El de quien envió o, si fue una entidad, el RUC o el DNI de quien la representa."
        inputProps={{ inputMode: 'numeric', autoComplete: 'off', maxLength: 15 }} />
      {error && <Alert severity="error" role="alert">{error}</Alert>}
      <Button type="submit" variant="contained" startIcon={<SearchIcon />} disabled={buscando} sx={{ py: 1.1, alignSelf: { xs: 'stretch', sm: 'flex-start' } }}>
        Consultar
      </Button>
    </Box>
  )
}
