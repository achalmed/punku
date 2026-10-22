/**
 * DETALLE de un documento recibido (2026-10-06): la ficha editable, el PDF (el
 * mismo visor de siempre), los documentos propios que lo responden y las
 * acciones — Responder (crea el borrador del oficio, vinculado), Agendar,
 * Crear tarea, Archivar o Reabrir. En pantallas muy anchas el PDF va en su
 * propia columna (`pdfAparte`); si no, en una pestaña.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import Alert from '@mui/material/Alert'
import Tabs from '@mui/material/Tabs'
import Tab from '@mui/material/Tab'
import LinearProgress from '@mui/material/LinearProgress'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import Autocomplete from '@mui/material/Autocomplete'
import TextField from '@mui/material/TextField'
import ReplyOutlinedIcon from '@mui/icons-material/ReplyOutlined'
import EventOutlinedIcon from '@mui/icons-material/EventOutlined'
import AddTaskOutlinedIcon from '@mui/icons-material/AddTaskOutlined'
import ArchiveOutlinedIcon from '@mui/icons-material/ArchiveOutlined'
import UnarchiveOutlinedIcon from '@mui/icons-material/UnarchiveOutlined'
import DownloadIcon from '@mui/icons-material/Download'
import LinkOffIcon from '@mui/icons-material/LinkOff'
import CloseIcon from '@mui/icons-material/Close'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { MapaLocal, PALETA, VisorPdf, api, descargarArchivo, hay } from '@qillqa/tiqsi'
import { buscarDocumentos, hayAgenda, hayDocumentos, hayTareas, hoyIso, origenDePegado, proponerEvento, registrarPegado, rutaDe, type MiembroEquipo, type PegadoAplicado } from './apoyo'
import { Actuaciones, PegarResultado, hayActuaciones } from './piezas'
import PropuestaEvento from './PropuestaEvento'
import FormularioFicha from './FormularioFicha'
import PanelMesaVirtual from './PanelMesaVirtual'
import { datosDe, estadoDe, fechaCorta, textoPlazo, type DatosFicha, type EventoPropuesto, type FichaCompleta, type PropuestasEntrada } from './modelo'

interface DocVinculo {
  id: number
  numero_completo: string
  asunto: string
  estado: string
}

export default function DetalleEntrada({
  id,
  equipo,
  campanas,
  pdfAparte = false,
  soloLectura = false,
  alCambiar,
  alCerrar,
  alAvisar,
}: {
  id: number
  equipo: MiembroEquipo[]
  campanas: string[]
  /** El PDF lo muestra la página en otra columna: aquí no va. */
  pdfAparte?: boolean
  soloLectura?: boolean
  /** Algo cambió (la lista se refresca). */
  alCambiar: () => void
  alCerrar?: () => void
  alAvisar: (tipo: 'success' | 'error' | 'info', texto: string) => void
}) {
  const navegar = useNavigate()
  const [ficha, setFicha] = useState<FichaCompleta | null>(null)
  const [datos, setDatos] = useState<DatosFicha | null>(null)
  const [cargando, setCargando] = useState(true)
  const [ocupado, setOcupado] = useState(false)
  const [pestana, setPestana] = useState<'mesa' | 'ficha' | 'pdf' | 'vinculos' | 'seguimiento' | 'texto'>('ficha')
  const [opcionesDoc, setOpcionesDoc] = useState<DocVinculo[]>([])
  const abrioMesa = useRef<number | null>(null)

  const cargar = useCallback(async () => {
    setCargando(true)
    try {
      const f = await api<FichaCompleta>(`/api/entradas/${id}`)
      // Lo que llegó por la mesa de partes virtual abre en su pestaña (una vez por recibido).
      if (f.via === 'mesa_virtual' && abrioMesa.current !== id) {
        abrioMesa.current = id
        setPestana('mesa')
      }
      setFicha(f)
      setDatos(datosDe(f))
    } catch (e) {
      alAvisar('error', e instanceof Error ? e.message : 'No se pudo abrir el documento recibido.')
    } finally {
      setCargando(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])
  useEffect(() => {
    setPestana('ficha')
    void cargar()
  }, [cargar])

  const original = useMemo(() => (ficha ? datosDe(ficha) : null), [ficha])
  const cambios = useMemo(() => {
    if (!datos || !original) return {}
    return Object.fromEntries(Object.entries(datos).filter(([k, v]) => original[k as keyof DatosFicha] !== v))
  }, [datos, original])
  const sucio = Object.keys(cambios).length > 0
  // El pegado aplicado a la ficha (constancia al guardar) y el evento que propone.
  const [pegado, setPegado] = useState<PegadoAplicado | null>(null)
  const [evento, setEvento] = useState<{ ev: EventoPropuesto; existente: PropuestasEntrada['evento_existente']; crear: boolean } | null>(null)

  const guardar = async () => {
    setOcupado(true)
    try {
      // Lo que cambió a mano queda como 'persona'; lo aceptado del pegado, como 'pegado'.
      const origen_campos = { ...Object.fromEntries(Object.keys(cambios).map((k) => [k, 'persona' as const])), ...(pegado ? origenDePegado(pegado.aceptadas) : {}) }
      await api(`/api/entradas/${id}`, { method: 'PUT', body: JSON.stringify({ ...cambios, origen_campos }) })
      if (pegado) {
        const { aceptadas, rechazadas, ...resto } = pegado
        void registrarPegado({ ...resto, rechazados: rechazadas, entidad: `entrada:${id}`, campos_aplicados: Object.fromEntries([...aceptadas].map((k) => [k, (datos as unknown as Record<string, unknown>)[k]])) })
        setPegado(null)
      }
      if (evento?.crear && hayAgenda()) {
        try {
          // La Agenda es de Tareas y Agenda: el anfitrión la propone o la vincula («agenda.proponer_evento»).
          await proponerEvento(evento.ev as unknown as Record<string, unknown>, evento.existente?.id ?? null, `entrada:${id}`)
        } catch {
          alAvisar('error', 'La ficha se guardó, pero no se pudo crear el evento en la Agenda.')
        }
        setEvento(null)
      }
      alAvisar('success', 'Ficha guardada.')
      await cargar()
      alCambiar()
    } catch (e) {
      alAvisar('error', e instanceof Error ? e.message : 'No se pudo guardar la ficha.')
    } finally {
      setOcupado(false)
    }
  }

  const accion = async (ruta: string, mensaje: string, cuerpo?: object) => {
    setOcupado(true)
    try {
      const r = await api<{ id?: number; ya_existia?: boolean }>(ruta, { method: 'POST', body: JSON.stringify(cuerpo ?? {}) })
      alAvisar('success', mensaje)
      await cargar()
      alCambiar()
      return r
    } catch (e) {
      alAvisar('error', e instanceof Error ? e.message : 'No se pudo completar la acción.')
      return null
    } finally {
      setOcupado(false)
    }
  }

  const responder = async () => {
    if (sucio) await guardar()
    const r = await accion(`/api/entradas/${id}/responder`, 'Borrador del oficio de respuesta creado y vinculado.')
    const ruta = r?.id ? rutaDe(`doc:${r.id}`) : null
    if (ruta) navegar(ruta)
  }

  const desvincular = async (docId: number) => {
    setOcupado(true)
    try {
      await api(`/api/entradas/${id}/vincular/${docId}`, { method: 'DELETE' })
      await cargar()
      alCambiar()
    } catch (e) {
      alAvisar('error', e instanceof Error ? e.message : 'No se pudo quitar el vínculo.')
    } finally {
      setOcupado(false)
    }
  }

  const buscarDocs = async (q: string) => {
    if (q.trim().length < 2) return setOpcionesDoc([])
    try {
      setOpcionesDoc(await buscarDocumentos<DocVinculo>(q))
    } catch {
      setOpcionesDoc([])
    }
  }

  if (cargando && !ficha) return <LinearProgress />
  if (!ficha || !datos) return null
  const est = estadoDe(ficha.estado)
  const hoy = hoyIso()
  const abierta = ficha.estado === 'nueva' || ficha.estado === 'en_atencion'
  const rutaPdf = ficha.tiene_pdf ? `/api/entradas/${id}/pdf` : ''

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, height: '100%' }}>
      {(cargando || ocupado) && <LinearProgress sx={{ mb: -0.5 }} />}
      {/* Cabecera: qué es, de quién, en qué estado. */}
      <Box sx={{ p: { xs: 1.5, sm: 2 }, pb: 1, borderBottom: '1px solid', borderColor: 'divider' }}>
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1 }}>
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', alignItems: 'center', mb: 0.5 }}>
              <Chip size="small" label={est.t} sx={{ height: 22, bgcolor: `${est.color}1A`, color: est.color, fontWeight: 600 }} />
              {ficha.mesa && <Chip size="small" variant="outlined" label={`Mesa virtual · ${ficha.mesa.expediente}`} sx={{ height: 22, borderColor: PALETA.guinda, color: PALETA.guinda }} />}
              {ficha.std_numero && <Chip size="small" variant="outlined" label={`STD ${ficha.std_numero}`} sx={{ height: 22 }} />}
              {ficha.campana && <Chip size="small" variant="outlined" label={ficha.campana} sx={{ height: 22 }} />}
              {ficha.plazo && abierta && (
                <Chip size="small" variant="outlined" label={`${textoPlazo(ficha.plazo, hoy)} (${fechaCorta(ficha.plazo)})`}
                  sx={{ height: 22, ...(ficha.vencida ? { color: PALETA.error, borderColor: PALETA.error } : ficha.por_vencer ? { color: PALETA.avisoOscuro, borderColor: PALETA.avisoBorde } : {}) }} />
              )}
            </Box>
            <Typography component="h2" sx={{ fontWeight: 650, fontSize: { xs: 16, sm: 17 }, lineHeight: 1.3, wordBreak: 'break-word' }}>
              {ficha.asunto || ficha.documento || ficha.nombre_original}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ wordBreak: 'break-word' }}>
              {[ficha.documento, ficha.remitente, ficha.fecha_documento && `del ${fechaCorta(ficha.fecha_documento)}`, ficha.fecha_recepcion && `recibido el ${fechaCorta(ficha.fecha_recepcion)}`]
                .filter(Boolean).join(' · ')}
            </Typography>
          </Box>
          {alCerrar && (
            <IconButton onClick={alCerrar} aria-label="Cerrar el detalle" size="small">
              <CloseIcon />
            </IconButton>
          )}
        </Box>
        {/* 2026-10-06: quitado el aviso «Sin respuesta: el plazo venció…»: lo dice el chip rojo del plazo. */}
        {ficha.respuesta && (
          <Alert severity={ficha.estado === 'respondida' ? 'success' : 'info'} variant="outlined" sx={{ mt: 1, py: 0 }}
            action={rutaDe(`doc:${ficha.respuesta.id}`) && <Button size="small" color="inherit" onClick={() => navegar(rutaDe(`doc:${ficha.respuesta!.id}`)!)}>Abrir</Button>}>
            {ficha.estado === 'respondida' ? 'Respondido con' : 'Respuesta en curso:'} {ficha.respuesta.numero} ({ficha.respuesta.estado.toLowerCase()})
          </Alert>
        )}
        {/* Acciones. «Agendar» y «Crear tarea» abren los módulos de Agenda y Tareas con la entrada. */}
        {!soloLectura && (
          <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mt: 1.25 }}>
            {/* 2026-10-06: con respuesta, se abre desde el «Abrir» de su aviso (antes había dos botones). */}
            {abierta && !ficha.respuesta && hayDocumentos() && (
              <Button size="small" variant="contained" startIcon={<ReplyOutlinedIcon />} onClick={() => void responder()} disabled={ocupado}>
                Responder
              </Button>
            )}
            {/* Tareas y Agenda, si está (sola, no): sus pantallas, con el recibido. */}
            {hayTareas() && (
              <>
                <Button size="small" variant="outlined" startIcon={<EventOutlinedIcon />} onClick={() => navegar(`/agenda?nuevo=1&entrada=${id}`)}>
                  Agendar
                </Button>
                <Button size="small" variant="outlined" startIcon={<AddTaskOutlinedIcon />} onClick={() => navegar(`/tareas?nueva=1&entrada=${id}`)}>
                  Crear tarea
                </Button>
              </>
            )}
            {ficha.estado !== 'archivada' ? (
              <Button size="small" color="inherit" startIcon={<ArchiveOutlinedIcon />} disabled={ocupado}
                onClick={() => void accion(`/api/entradas/${id}/archivar`, 'Archivado. Se puede reabrir cuando haga falta.')}>
                Archivar
              </Button>
            ) : (
              <Button size="small" color="inherit" startIcon={<UnarchiveOutlinedIcon />} disabled={ocupado}
                onClick={() => void accion(`/api/entradas/${id}/reabrir`, 'Reabierto.')}>
                Reabrir
              </Button>
            )}
            {ficha.tiene_pdf && (
              <Tooltip title="Descargar el PDF">
                <IconButton size="small" onClick={() => void descargarArchivo(`/api/entradas/${id}/pdf`)} aria-label="Descargar el PDF">
                  <DownloadIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
            <Tooltip title={`Copiar cómo citarlo en la Referencia: «${ficha.cita}»`}>
              <IconButton size="small" aria-label="Copiar la cita para la Referencia"
                onClick={() => void navigator.clipboard?.writeText(ficha.cita).then(() => alAvisar('info', 'Cita copiada: péguela en la Referencia del oficio.'))}>
                <ContentCopyIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Box>
        )}
      </Box>

      <Tabs value={pestana} onChange={(_, v) => setPestana(v)} variant="scrollable" allowScrollButtonsMobile sx={{ px: 1, minHeight: 40, borderBottom: '1px solid', borderColor: 'divider', '& .MuiTab-root': { minHeight: 40, textTransform: 'none' } }}>
        {ficha.via === 'mesa_virtual' && <Tab value="mesa" label="Mesa virtual" />}
        <Tab value="ficha" label="Ficha" />
        {!pdfAparte && <Tab value="pdf" label="PDF" />}
        {/* Sin documentos propios, mapa ni seguimiento (la Mesa de Partes sola), estas pestañas no tienen qué mostrar. */}
        {(ficha.vinculos.length > 0 || hayDocumentos() || hay('MapaLocal')) && (
          <Tab value="vinculos" label={`Respuestas y relaciones${ficha.vinculos.length ? ` (${ficha.vinculos.length})` : ''}`} />
        )}
        {hayActuaciones() && <Tab value="seguimiento" label="Seguimiento" />}
        <Tab value="texto" label="Texto" />
      </Tabs>

      <Box sx={{ flex: 1, minHeight: 0, overflow: 'auto', p: { xs: 1.5, sm: 2 } }}>
        {pestana === 'mesa' && ficha.via === 'mesa_virtual' && (
          <PanelMesaVirtual
            entradaId={id}
            soloLectura={soloLectura}
            respuesta={ficha.respuesta}
            vinculos={ficha.vinculos}
            alCambiar={() => { void cargar(); alCambiar() }}
            alAvisar={alAvisar}
          />
        )}
        {pestana === 'ficha' && (
          <>
            {!soloLectura && (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mb: 1.5 }}>
                <PegarResultado<PropuestasEntrada>
                  ruta="/api/entradas/pegar"
                  tipos={['documento-recibido']}
                  actual={datos as unknown as Record<string, unknown>}
                  cuerpoExtra={{ excluir_id: id }}
                  alAplicar={(campos, aplicado, r) => {
                    setDatos(campos as unknown as DatosFicha)
                    setPegado(aplicado)
                    setEvento(r.propuestas?.evento ? { ev: r.propuestas.evento, existente: r.propuestas.evento_existente ?? null, crear: true } : null)
                  }}
                  propuestas={(r) => (
                    <>
                      {r.propuestas?.duplicado && (
                        <Alert severity="warning" sx={{ py: 0 }}>El n.º STD {r.propuestas.duplicado.std_numero} ya es de otro recibido: «{r.propuestas.duplicado.asunto}».</Alert>
                      )}
                      {r.propuestas?.responde_a && <Alert severity="info" sx={{ py: 0 }}>Responde a nuestro {r.propuestas.responde_a.numero}: al guardar queda vinculado.</Alert>}
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
                {evento && <PropuestaEvento evento={evento.ev} existente={evento.existente} marcado={evento.crear} alMarcar={(v) => setEvento({ ...evento, crear: v })} />}
              </Box>
            )}
            <FormularioFicha valor={datos} alCambiar={(c) => setDatos({ ...datos, ...c })} equipo={equipo} campanas={campanas} soloLectura={soloLectura} />
            {Object.keys(ficha.origen_campos ?? {}).length > 0 && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                Origen de los datos: {(['documento', 'pegado', 'persona'] as const).map((o) => {
                  const n = Object.values(ficha.origen_campos).filter((x) => x === o).length
                  return n ? `${n} ${o === 'documento' ? 'leídos del PDF' : o === 'pegado' ? 'del resultado del prompt' : 'escritos a mano'}` : ''
                }).filter(Boolean).join(' · ')}
              </Typography>
            )}
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
              {[ficha.nombre_original && `Archivo: ${ficha.nombre_original}`, ficha.paginas && `${ficha.paginas} pág.`, ficha.creado_por && `registrado por ${ficha.creado_por}`]
                .filter(Boolean).join(' · ')}
            </Typography>
          </>
        )}
        {pestana === 'pdf' && !pdfAparte && (
          <VisorPdf ruta={rutaPdf} alto="70vh" nombre={ficha.nombre_original || 'recibido.pdf'}
            vacio={<Typography color="text.secondary">El PDF no está en el archivo documental.</Typography>} />
        )}
        {pestana === 'vinculos' && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            {ficha.vinculos.length === 0 && (
              <Typography variant="body2" color="text.secondary">
                Sin respuesta vinculada. Use «Responder» o cítelo en una Referencia.
              </Typography>
            )}
            {ficha.vinculos.map((v) => (
              <Box key={v.relacion_id} sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 1, border: '1px solid', borderColor: 'divider', borderRadius: 1.5 }}>
                <Box sx={{ minWidth: 0, flex: 1, cursor: 'pointer' }} onClick={() => { const r = rutaDe(`doc:${v.id}`); if (r) navegar(r) }}>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>{v.numero}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {v.asunto} · {v.estado.toLowerCase()} · {v.contexto === 'referencia' ? 'la cita en su Referencia' : v.contexto === 'responder' ? 'creado con «Responder»' : 'vinculado a mano'}
                  </Typography>
                </Box>
                {!soloLectura && (
                  <Tooltip title="Quitar el vínculo">
                    <IconButton size="small" onClick={() => void desvincular(v.id)} aria-label="Quitar el vínculo"><LinkOffIcon fontSize="small" /></IconButton>
                  </Tooltip>
                )}
              </Box>
            ))}
            {!soloLectura && hayDocumentos() && (
              <Autocomplete
                options={opcionesDoc}
                getOptionLabel={(o) => `${o.numero_completo} — ${o.asunto}`}
                filterOptions={(x) => x}
                onInputChange={(_, v) => void buscarDocs(v)}
                onChange={(_, o) => o && void accion(`/api/entradas/${id}/vincular`, `${o.numero_completo} quedó vinculado como respuesta.`, { documento_id: o.id })}
                renderInput={(p) => <TextField {...p} size="small" label="Vincular un documento propio que lo responde" placeholder="Número o asunto" />}
                noOptionsText="Escriba el número o parte del asunto"
              />
            )}
            <MapaLocal foco={`entrada:${id}`} alto={220} titulo="Relaciones de este documento recibido" />
          </Box>
        )}
        {pestana === 'seguimiento' && (
          <Actuaciones entidad={`entrada:${id}`} soloLectura={soloLectura} />
        )}
        {pestana === 'texto' && (
          <Typography component="pre" sx={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: 13.5, color: 'text.secondary', m: 0 }}>
            {ficha.texto || 'El PDF no tiene capa de texto (es un escaneo).'}
          </Typography>
        )}
      </Box>

      {sucio && !soloLectura && (
        <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end', p: 1.25, borderTop: '1px solid', borderColor: 'divider', bgcolor: PALETA.superficieTenue }}>
          <Button color="inherit" onClick={() => { setDatos(original); setPegado(null); setEvento(null) }} disabled={ocupado}>Descartar</Button>
          <Button variant="contained" onClick={() => void guardar()} disabled={ocupado}>Guardar cambios</Button>
        </Box>
      )}
    </Box>
  )
}
