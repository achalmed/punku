/**
 * SUBIR DOCUMENTOS RECIBIDOS (2026-10-06): arrastrar o elegir uno o varios PDF (Word e
 * imágenes se pasan a PDF) → el servidor lee cada uno y propone su FICHA (n.º STD,
 * remitente, fecha, asunto, atención, plazo) → se revisa y corrige aquí, con el PDF a la
 * vista → «Registrar». Las partes de un mismo envío se UNEN en un solo documento; el
 * RESUMEN que el equipo escribió en el grupo (prompt de recepción) se pega y llena la
 * ficha; si es una agenda, crea además el evento, vinculado. Un duplicado (mismo archivo
 * o mismo n.º STD, también dentro del lote) se avisa y no se registra.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import Button from '@mui/material/Button'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Alert from '@mui/material/Alert'
import Checkbox from '@mui/material/Checkbox'
import Chip from '@mui/material/Chip'
import Collapse from '@mui/material/Collapse'
import LinearProgress from '@mui/material/LinearProgress'
import TextField from '@mui/material/TextField'
import MenuItem from '@mui/material/MenuItem'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import useMediaQuery from '@mui/material/useMediaQuery'
import { useTheme } from '@mui/material/styles'
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import PictureAsPdfOutlinedIcon from '@mui/icons-material/PictureAsPdfOutlined'
import EventOutlinedIcon from '@mui/icons-material/EventOutlined'
import { ErrorApi, PALETA, VisorPdf, api, subirArchivo } from '@qillqa/tiqsi'
import { origenDePegado, proponerEvento, registrarPegado, type MiembroEquipo, type PegadoAplicado } from './apoyo'
import { PegarResultado } from './piezas'
import FormularioFicha from './FormularioFicha'
import PropuestaEvento, { cuandoDe } from './PropuestaEvento'
import { atencionDe, datosDe, fechaCorta, type Analizado, type DatosFicha, type EventoPropuesto, type PropuestasEntrada } from './modelo'

/** Cómo llega el pegado a la subida (entrada doble, fase 9.5): la caja abierta en la primera
 *  ficha y, si viene del chat (`?pegar=<id>`), el texto ya puesto y leído. */
export interface PegadoEnSubida {
  abrir: boolean
  texto?: string
}

interface Fila {
  a: Analizado
  datos: DatosFicha | null
  registrar: boolean
  abierta: boolean
  verPdf: boolean
  /** La caja de pegado abierta de entrada (primera fila de una subida «desde el prompt»). */
  pegarAbierto?: boolean
  /** Texto del chat que se lee solo en esa caja. */
  textoInicial?: string
  /** El resultado del prompt pegado y aplicado a la ficha (constancia tras registrar). */
  pegado: PegadoAplicado | null
  /** Evento que propone el pegado; se crea al registrar si `crearEvento`. */
  evento: EventoPropuesto | null
  /** Si el evento ya está en la Agenda, se vincula a ese en vez de crearlo. */
  existente: PropuestasEntrada['evento_existente']
  crearEvento: boolean
}

const filaDe = (a: Analizado, abierta: boolean): Fila => ({
  a,
  datos: a.ficha ? datosDe(a.ficha) : null,
  registrar: !a.error && !a.duplicado,
  abierta,
  verPdf: false,
  pegado: null,
  evento: null,
  existente: null,
  crearEvento: false,
})

/** Lo que se acepta al soltar: PDF, Word e imágenes (el servidor pasa a PDF lo que no lo es). */
export const ADMITIDOS = /\.(pdf|docx?|odt|rtf|jpe?g|png|webp)$/i

/** Zona para soltar PDF (o tocar y elegirlos: en el celular no hay arrastre). */
export function ZonaSoltar({ alElegir, compacta = false }: { alElegir: (f: File[]) => void; compacta?: boolean }) {
  const [encima, setEncima] = useState(false)
  return (
    <Box
      component="label"
      onDragOver={(e: React.DragEvent) => {
        e.preventDefault()
        setEncima(true)
      }}
      onDragLeave={() => setEncima(false)}
      onDrop={(e: React.DragEvent) => {
        e.preventDefault()
        setEncima(false)
        alElegir(Array.from(e.dataTransfer.files).filter((f) => ADMITIDOS.test(f.name)))
      }}
      sx={{
        display: 'flex', flexDirection: compacta ? 'row' : 'column', alignItems: 'center', justifyContent: 'center',
        gap: 1, p: compacta ? 1.5 : 4, borderRadius: 2, cursor: 'pointer', textAlign: 'center',
        border: '2px dashed', borderColor: encima ? 'primary.main' : PALETA.bordeFuerte,
        bgcolor: encima ? PALETA.guindaSuave : PALETA.superficieTenue, transition: 'all .15s',
      }}
    >
      <UploadFileOutlinedIcon sx={{ fontSize: compacta ? 22 : 40, color: 'primary.main' }} />
      <Box>
        <Typography sx={{ fontWeight: 600, fontSize: compacta ? 14 : 15 }}>Arrastre aquí los PDF recibidos</Typography>
        <Typography variant="caption" color="text.secondary">
          o toque para elegirlos · también Word e imágenes · el n.º STD se lee del nombre
        </Typography>
      </Box>
      <input
        type="file"
        hidden
        multiple
        accept="application/pdf,.pdf,.docx,.doc,.odt,.rtf,image/jpeg,image/png,image/webp"
        onChange={(e) => {
          alElegir(Array.from(e.target.files ?? []))
          e.target.value = ''
        }}
      />
    </Box>
  )
}

export default function SubirEntradas({
  abierto,
  archivos,
  equipo,
  campanas,
  alCerrar,
  alTerminar,
  pegado = null,
}: {
  abierto: boolean
  /** PDF ya elegidos (soltados sobre la página). */
  archivos: File[]
  /** Pegado que acompaña a esta subida: va a la primera ficha que se lea. */
  pegado?: PegadoEnSubida | null
  equipo: MiembroEquipo[]
  campanas: string[]
  alCerrar: () => void
  alTerminar: (creadas: number[]) => void
}) {
  const tema = useTheme()
  const celular = useMediaQuery(tema.breakpoints.down('sm'))
  const navegar = useNavigate()
  const [filas, setFilas] = useState<Fila[]>([])
  const [analizando, setAnalizando] = useState(false)
  const [guardando, setGuardando] = useState(false)
  const [uniendo, setUniendo] = useState(false)
  const [error, setError] = useState('')
  const [resultado, setResultado] = useState<{ creadas: number[]; duplicadas: { nombre: string; motivo: string }[] } | null>(null)
  const [campanaLote, setCampanaLote] = useState('')
  const [responsableLote, setResponsableLote] = useState<number | ''>('')
  // El pegado pendiente se gasta en la primera fila que aparezca.
  const pegadoPendiente = useRef<PegadoEnSubida | null>(null)

  const analizar = async (lista: File[]) => {
    if (!lista.length) return
    setAnalizando(true)
    setError('')
    setResultado(null)
    const fd = new FormData()
    lista.forEach((f) => fd.append('archivos', f))
    try {
      const r = await subirArchivo<Analizado[]>('/api/entradas/analizar', fd)
      setFilas((antes) => {
        const nuevas = r.map((a) => filaDe(a, r.length === 1))
        const p = pegadoPendiente.current
        if (p && nuevas[0]?.datos) {
          nuevas[0] = { ...nuevas[0], abierta: true, pegarAbierto: p.abrir, textoInicial: p.texto }
          pegadoPendiente.current = null
        }
        return [...antes, ...nuevas]
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudieron leer los PDF.')
    } finally {
      setAnalizando(false)
    }
  }

  // Lo soltado sobre la página entra al abrir el diálogo.
  useEffect(() => {
    if (abierto) {
      setFilas([])
      setResultado(null)
      setCampanaLote('')
      setResponsableLote('')
      pegadoPendiente.current = pegado
      void analizar(archivos)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [abierto])

  const elegidas = useMemo(() => filas.filter((f) => f.registrar && f.datos && f.a.token), [filas])
  const cambiar = (i: number, cambio: Partial<Fila>) => setFilas((fs) => fs.map((f, j) => (j === i ? { ...f, ...cambio } : f)))

  const aplicarLote = () =>
    setFilas((fs) =>
      fs.map((f) =>
        f.datos && f.registrar
          ? {
              ...f,
              datos: {
                ...f.datos,
                ...(campanaLote.trim() ? { campana: campanaLote.trim() } : {}),
                ...(responsableLote !== '' ? { responsable_id: Number(responsableLote) } : {}),
              },
            }
          : f,
      ),
    )

  // Las partes marcadas de un mismo envío → un solo PDF, en el orden de la lista.
  const marcadas = filas.filter((f) => f.registrar && f.a.token)
  const unirMarcadas = async () => {
    setUniendo(true)
    setError('')
    try {
      const a = await api<Analizado>('/api/entradas/unir', {
        method: 'POST',
        body: JSON.stringify({ tokens: marcadas.map((f) => f.a.token), nombre: marcadas[0].a.nombre }),
      })
      setFilas((fs) => {
        const primera = fs.findIndex((f) => f.registrar && f.a.token)
        const resto = fs.filter((f) => !(f.registrar && f.a.token))
        resto.splice(Math.min(primera, resto.length), 0, filaDe(a, true))
        return resto
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'No se pudieron unir.')
    } finally {
      setUniendo(false)
    }
  }

  /** De dónde salió cada campo: lo que la ficha automática leyó del PDF y lo aceptado del pegado. */
  const origenDe = (f: Fila): Record<string, 'documento' | 'pegado'> => ({
    ...Object.fromEntries(Object.entries(f.a.ficha ?? {}).filter(([k, v]) => k in (f.datos ?? {}) && v !== '' && v != null).map(([k]) => [k, 'documento' as const])),
    ...(f.pegado ? origenDePegado(f.pegado.aceptadas) : {}),
  })

  const registrar = async () => {
    setGuardando(true)
    setError('')
    try {
      const r = await api<{ creadas: number[]; duplicadas: { nombre: string; motivo: string }[]; por_token: Record<string, number> }>('/api/entradas', {
        method: 'POST',
        body: JSON.stringify({ items: elegidas.map((f) => ({ token: f.a.token, nombre: f.a.nombre, ...f.datos, origen_campos: origenDe(f) })) }),
      })
      // Constancia de cada pegado aplicado, sobre la entrada que salió de ese PDF.
      for (const f of elegidas) {
        const eid = f.a.token ? r.por_token?.[f.a.token] : undefined
        if (f.pegado && eid) {
          const { aceptadas, rechazadas, ...resto } = f.pegado
          void registrarPegado({
            ...resto, rechazados: rechazadas, entidad: `entrada:${eid}`,
            campos_aplicados: Object.fromEntries([...aceptadas].map((k) => [k, (f.datos as unknown as Record<string, unknown>)[k]])),
          })
        }
      }
      // El evento de cada agenda, vinculado a su entrada (el mismo alta de la Agenda).
      const sinEvento: string[] = []
      for (const f of elegidas) {
        const eid = f.a.token ? r.por_token?.[f.a.token] : undefined
        if (!f.evento || !f.crearEvento || !eid) continue
        try {
          // La Agenda es de Tareas y Agenda: el anfitrión la propone o la vincula («agenda.proponer_evento»).
          await proponerEvento(f.evento as unknown as Record<string, unknown>, f.existente?.id ?? null, `entrada:${eid}`)
        } catch {
          sinEvento.push(f.evento.titulo)
        }
      }
      setResultado(r)
      if (r.creadas.length) alTerminar(r.creadas)
      if (sinEvento.length) setError(`Se registraron, pero no se creó en la Agenda: ${sinEvento.join('; ')}.`)
      else if (!r.duplicadas.length) alCerrar()
    } catch (e) {
      setError(e instanceof ErrorApi || e instanceof Error ? e.message : 'No se pudieron registrar.')
    } finally {
      setGuardando(false)
    }
  }

  return (
    <Dialog open={abierto} onClose={guardando ? undefined : alCerrar} fullScreen={celular} maxWidth="lg" fullWidth>
      <DialogTitle sx={{ pb: 1 }}>
        Registrar documentos recibidos
        <Typography variant="body2" color="text.secondary">
          Revise la ficha que se leyó de cada PDF; corrija lo que haga falta antes de registrar.
        </Typography>
      </DialogTitle>
      <DialogContent dividers sx={{ px: { xs: 1.5, sm: 3 } }}>
        {analizando && <LinearProgress sx={{ mb: 1.5 }} />}
        {error && <Alert severity="error" sx={{ mb: 1.5 }}>{error}</Alert>}
        {resultado?.duplicadas.length ? (
          <Alert severity="warning" sx={{ mb: 1.5 }}>
            Se registraron {resultado.creadas.length}. No se registraron:{' '}
            {resultado.duplicadas.map((d) => `${d.nombre} (${d.motivo})`).join('; ')}.
          </Alert>
        ) : null}

        {pegado && filas.length === 0 && !analizando && (
          <Alert severity="info" sx={{ mb: 1.5 }}>Suba el PDF del recibido: el resultado del prompt se aplica a su ficha.</Alert>
        )}
        <ZonaSoltar compacta={filas.length > 0} alElegir={(f) => void analizar(f)} />

        {filas.length > 1 && (
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center', mt: 1.5, p: 1.25, borderRadius: 2, bgcolor: PALETA.superficieTenue, border: '1px solid', borderColor: 'divider' }}>
            <Typography variant="body2" sx={{ fontWeight: 600, mr: 0.5 }}>A todos los marcados:</Typography>
            <TextField size="small" label="Campaña" value={campanaLote} onChange={(e) => setCampanaLote(e.target.value)}
              inputProps={{ list: 'campanas-entradas' }} sx={{ minWidth: 200, flex: '1 1 200px' }} />
            <datalist id="campanas-entradas">{campanas.map((c) => <option key={c} value={c} />)}</datalist>
            <TextField size="small" select label="Responsable" value={responsableLote}
              onChange={(e) => setResponsableLote(e.target.value === '' ? '' : Number(e.target.value))} sx={{ minWidth: 200, flex: '1 1 200px' }}>
              <MenuItem value=""><em>Sin cambiar</em></MenuItem>
              {equipo.map((m) => <MenuItem key={m.id} value={m.id}>{m.nombre_completo}</MenuItem>)}
            </TextField>
            <Button size="small" variant="outlined" onClick={aplicarLote} disabled={!campanaLote.trim() && responsableLote === ''}>
              Aplicar
            </Button>
            <Tooltip title="Partes de un mismo envío (citación, agenda, proyectos): un solo documento, en este orden">
              <span>
                <Button size="small" variant="outlined" onClick={() => void unirMarcadas()} disabled={uniendo || marcadas.length < 2}>
                  {uniendo ? 'Uniendo…' : marcadas.length >= 2 ? `Unir ${marcadas.length} en un documento` : 'Unir en un documento'}
                </Button>
              </span>
            </Tooltip>
          </Box>
        )}

        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mt: 1.5 }}>
          {filas.map((f, i) => {
            const fi = f.a.ficha
            return (
              <Box key={`${f.a.token ?? f.a.nombre}-${i}`} sx={{ border: '1px solid', borderColor: f.a.duplicado || f.a.error ? PALETA.avisoBorde : 'divider', borderRadius: 2, bgcolor: 'background.paper', overflow: 'hidden' }}>
                <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5, p: 1 }}>
                  <Checkbox
                    checked={f.registrar}
                    disabled={!f.datos || Boolean(f.a.error) || Boolean(f.a.duplicado)}
                    onChange={(e) => cambiar(i, { registrar: e.target.checked })}
                    inputProps={{ 'aria-label': `Registrar ${f.a.nombre}` }}
                    sx={{ mt: -0.5 }}
                  />
                  <Box sx={{ minWidth: 0, flex: 1, cursor: f.datos ? 'pointer' : 'default' }} onClick={() => f.datos && cambiar(i, { abierta: !f.abierta })}>
                    <Typography sx={{ fontWeight: 600, fontSize: 14, wordBreak: 'break-word' }}>
                      {f.datos?.asunto || f.a.nombre}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', wordBreak: 'break-word' }}>
                      {[f.datos?.documento, f.datos?.std_numero && `STD ${f.datos.std_numero}`, f.datos?.remitente, fechaCorta(f.datos?.fecha_documento)]
                        .filter(Boolean).join(' · ') || f.a.nombre}
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
                      {f.datos && <Chip size="small" label={atencionDe(f.datos.atencion)} sx={{ height: 20, fontSize: 11.5 }} />}
                      {f.datos?.plazo && <Chip size="small" variant="outlined" label={`plazo ${fechaCorta(f.datos.plazo)}`} sx={{ height: 20, fontSize: 11.5 }} />}
                      {f.datos?.campana && <Chip size="small" variant="outlined" label={f.datos.campana} sx={{ height: 20, fontSize: 11.5 }} />}
                      {f.a.partes && <Chip size="small" variant="outlined" label={`${f.a.partes} archivos unidos`} sx={{ height: 20, fontSize: 11.5 }} />}
                      {f.evento && f.crearEvento && <Chip size="small" variant="outlined" icon={<EventOutlinedIcon />} label={`${f.existente ? 'En la Agenda' : 'Agenda'}: ${cuandoDe(f.evento)}`} sx={{ height: 20, fontSize: 11.5 }} />}
                      {f.a.copia_de_descarga && <Chip size="small" variant="outlined" label="descarga repetida «(1)»" sx={{ height: 20, fontSize: 11.5, color: PALETA.avisoOscuro, borderColor: PALETA.avisoBorde }} />}
                      {fi?.avisos.map((a) => (
                        <Chip key={a} size="small" variant="outlined" label={a} sx={{ height: 'auto', minHeight: 20, fontSize: 11.5, '& .MuiChip-label': { whiteSpace: 'normal' } }} />
                      ))}
                    </Box>
                    {f.a.error && <Alert severity="error" sx={{ mt: 0.75, py: 0 }}>{f.a.error}</Alert>}
                    {f.a.duplicado && (
                      <Alert
                        severity="warning"
                        sx={{ mt: 0.75, py: 0, bgcolor: PALETA.avisoFondo }}
                        action={f.a.duplicado.id ? (
                          <Button size="small" color="inherit" onClick={(e) => { e.stopPropagation(); alCerrar(); navegar(`/recibidos?ver=${f.a.duplicado!.id}`) }}>
                            Ver la registrada
                          </Button>
                        ) : undefined}
                      >
                        Ya está registrado: {f.a.duplicado.motivo}. No se vuelve a registrar.
                      </Alert>
                    )}
                  </Box>
                  {f.a.token && (
                    <Tooltip title="Ver el PDF">
                      <IconButton size="small" onClick={() => cambiar(i, { verPdf: !f.verPdf, abierta: true })} aria-label="Ver el PDF">
                        <PictureAsPdfOutlinedIcon fontSize="small" color={f.verPdf ? 'primary' : undefined} />
                      </IconButton>
                    </Tooltip>
                  )}
                  {f.datos && (
                    <IconButton size="small" onClick={() => cambiar(i, { abierta: !f.abierta })} aria-label={f.abierta ? 'Cerrar la ficha' : 'Abrir la ficha'}>
                      <ExpandMoreIcon fontSize="small" sx={{ transform: f.abierta ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }} />
                    </IconButton>
                  )}
                </Box>
                <Collapse in={f.abierta && Boolean(f.datos)} unmountOnExit>
                  {f.datos && (
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, px: { xs: 1.25, sm: 2 }, pb: 1.5 }}>
                      <PegarResultado<PropuestasEntrada>
                        ruta="/api/entradas/pegar"
                        tipos={['documento-recibido']}
                        actual={f.datos as unknown as Record<string, unknown>}
                        abiertoAlInicio={Boolean(f.pegarAbierto)}
                        textoInicial={f.textoInicial}
                        alAplicar={(campos, aplicado, r) =>
                          cambiar(i, {
                            // Aplicado el pegado, los avisos de la ficha automática («el asunto sale del nombre…») ya no valen.
                            a: f.a.ficha ? { ...f.a, ficha: { ...f.a.ficha, avisos: [] } } : f.a,
                            datos: campos as unknown as DatosFicha,
                            pegado: aplicado,
                            evento: r.propuestas?.evento ?? null,
                            existente: r.propuestas?.evento_existente ?? null,
                            crearEvento: Boolean(r.propuestas?.evento),
                          })
                        }
                        propuestas={(r) => (
                          <>
                            {r.propuestas?.duplicado && (
                              <Alert severity="warning" sx={{ py: 0 }}>
                                El n.º STD {r.propuestas.duplicado.std_numero} ya está registrado: «{r.propuestas.duplicado.asunto}» ({r.propuestas.duplicado.estado}).
                              </Alert>
                            )}
                            {r.propuestas?.responde_a && (
                              <Alert severity="info" sx={{ py: 0 }}>Responde a nuestro {r.propuestas.responde_a.numero}: al registrar queda vinculado y anotado en su seguimiento.</Alert>
                            )}
                            {r.propuestas?.expediente_doc && !r.propuestas?.responde_a && (
                              <Alert severity="info" sx={{ py: 0 }}>Nombra el expediente del {r.propuestas.expediente_doc.numero}: quedará vinculado a él.</Alert>
                            )}
                            {r.propuestas?.reunion_existente && (
                              <Alert severity="info" sx={{ py: 0 }}>Da seguimiento a «{r.propuestas.reunion_existente.titulo}» ({r.propuestas.reunion_existente.inicio.slice(0, 10)}), que ya está en la Agenda.</Alert>
                            )}
                            {r.propuestas?.requiere_revision && (
                              <Alert severity="warning" sx={{ py: 0 }}>La categoría no está clara: elíjala en la tabla; la ficha queda «Por revisar» hasta confirmarla.</Alert>
                            )}
                          </>
                        )}
                      />
                      {f.evento && <PropuestaEvento evento={f.evento} existente={f.existente} marcado={f.crearEvento} alMarcar={(v) => cambiar(i, { crearEvento: v })} />}
                    </Box>
                  )}
                  <Box sx={{ display: 'grid', gap: 2, p: { xs: 1.25, sm: 2 }, pt: 0.5, gridTemplateColumns: { xs: '1fr', md: f.verPdf ? 'minmax(0, 1fr) minmax(0, 1fr)' : '1fr' } }}>
                    {f.datos && (
                      <FormularioFicha
                        valor={f.datos}
                        alCambiar={(c) => cambiar(i, { datos: { ...f.datos!, ...c } })}
                        equipo={equipo}
                        campanas={campanas}
                        sinAsignacion
                      />
                    )}
                    {f.verPdf && f.a.token && (
                      <VisorPdf ruta={`/api/entradas/por-confirmar/${f.a.token}/pdf`} alto={celular ? 420 : 560} nombre={f.a.nombre} />
                    )}
                  </Box>
                </Collapse>
              </Box>
            )
          })}
        </Box>
      </DialogContent>
      <DialogActions sx={{ px: { xs: 1.5, sm: 3 }, py: 1.25, gap: 1, flexWrap: 'wrap' }}>
        <Typography variant="body2" color="text.secondary" sx={{ mr: 'auto' }}>
          {filas.length ? `${elegidas.length} de ${filas.length} por registrar` : ''}
        </Typography>
        <Button onClick={alCerrar} disabled={guardando} color="inherit">Cerrar</Button>
        <Button variant="contained" onClick={() => void registrar()} disabled={guardando || analizando || !elegidas.length}>
          {guardando ? 'Registrando…' : `Registrar ${elegidas.length || ''}`.trim()}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
