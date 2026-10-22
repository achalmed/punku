/**
 * RECIBIDOS — la bandeja de entrada del despacho (2026-10-06; backend/app/api/entradas.py).
 *
 * Lo que llega (cartas de gremios, pedidos de municipios, invitaciones, citaciones,
 * respuestas a nuestros oficios) se registra arrastrando sus PDF: el sistema lee la
 * ficha (n.º STD, remitente, fecha, asunto, atención, plazo) y avisa de los duplicados.
 * Cada entrada tiene responsable, plazo y estado; «Responder» crea el oficio vinculado.
 *
 *   ┌ filtros ─────────────────────────────────────────────────────────────┐
 *   │ lista                 │ ficha y acciones          │ PDF (≥ 1440 px)   │
 *   └───────────────────────┴───────────────────────────┴───────────────────┘
 * En el celular, la lista; el detalle se abre a pantalla completa.
 *
 * Consulta: `?ver=<id>` abre una entrada; `?subir=1` abre la subida (con `&pegar=<id de
 * mensaje>` del chat, la ficha de la primera fila se llena con ese resultado de prompt);
 * `?estado=`, `?vencidas=1`, `?responsable=yo|sin|<id>`, `?atencion=`, `?campana=` filtran.
 * Módulo propio desde el 2026-10-12 (fase 9.6): sus opciones están en `navegacion.ts`.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Button from '@mui/material/Button'
import TextField from '@mui/material/TextField'
import MenuItem from '@mui/material/MenuItem'
import InputAdornment from '@mui/material/InputAdornment'
import Chip from '@mui/material/Chip'
import ButtonBase from '@mui/material/ButtonBase'
import LinearProgress from '@mui/material/LinearProgress'
import Dialog from '@mui/material/Dialog'
import Snackbar from '@mui/material/Snackbar'
import Alert from '@mui/material/Alert'
import FormControlLabel from '@mui/material/FormControlLabel'
import Switch from '@mui/material/Switch'
import useMediaQuery from '@mui/material/useMediaQuery'
import { useTheme } from '@mui/material/styles'
import SearchIcon from '@mui/icons-material/Search'
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined'
import MoveToInboxOutlinedIcon from '@mui/icons-material/MoveToInboxOutlined'
import { BarraModulo, ElegirEntrada, Marco, PALETA, VisorPdf, api } from '@qillqa/tiqsi'
import { hoyIso, textoDeMensaje, type MiembroEquipo } from '../componentes/entradas/apoyo'
import SubirEntradas, { ADMITIDOS, ZonaSoltar, type PegadoEnSubida } from '../componentes/entradas/SubirEntradas'
import DetalleEntrada from '../componentes/entradas/DetalleEntrada'
import { ATENCIONES, ESTADOS, atencionDe, categoriaDe, estadoDe, fechaCorta, textoPlazo, type Entrada } from '../componentes/entradas/modelo'

type Aviso = { tipo: 'success' | 'error' | 'info'; texto: string }

function FilaEntrada({ e, activa, hoy, alElegir }: { e: Entrada; activa: boolean; hoy: string; alElegir: () => void }) {
  const est = estadoDe(e.estado)
  const abierta = e.estado === 'nueva' || e.estado === 'en_atencion'
  return (
    <ButtonBase
      onClick={alElegir}
      sx={{
        display: 'flex', width: '100%', alignItems: 'stretch', textAlign: 'left', gap: 1.25, px: 1.5, py: 1.1,
        borderBottom: '1px solid', borderColor: 'divider', bgcolor: activa ? PALETA.guindaSuave : 'transparent',
        '&:hover': { bgcolor: activa ? PALETA.guindaSuave : 'action.hover' },
      }}
    >
      {/* Sin barra lateral de color (2026-10-19): lo nuevo va en negrita y lo vencido o por vencer lo dice el plazo. */}
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'baseline' }}>
          <Typography variant="body2" sx={{ fontWeight: e.estado === 'nueva' ? 700 : 600, flex: 1, minWidth: 0 }} noWrap>
            {e.remitente || e.documento || 'Remitente sin identificar'}
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ flexShrink: 0 }}>{fechaCorta(e.fecha_recepcion)}</Typography>
        </Box>
        <Typography variant="body2" color="text.secondary" sx={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', lineHeight: 1.35 }}>
          {e.asunto || e.documento || e.nombre_original}
        </Typography>
        <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5, alignItems: 'center' }}>
          <Chip size="small" label={est.t} sx={{ height: 20, fontSize: 11.5, bgcolor: `${est.color}1A`, color: est.color, fontWeight: 600 }} />
          {e.mesa && (
            <Chip size="small" variant="outlined" label={`Mesa virtual · ${e.mesa.estado_texto}`}
              sx={{ height: 20, fontSize: 11.5, ...(e.mesa.vencido ? { color: PALETA.error, borderColor: PALETA.error } : e.mesa.estado === 'observado' ? { color: PALETA.avisoOscuro, borderColor: PALETA.avisoBorde } : { color: PALETA.guinda, borderColor: PALETA.guinda }) }} />
          )}
          <Chip size="small" variant="outlined" label={atencionDe(e.atencion)} sx={{ height: 20, fontSize: 11.5 }} />
          {e.categoria && <Chip size="small" variant="outlined" label={categoriaDe(e.categoria)} sx={{ height: 20, fontSize: 11.5 }} />}
          {e.requiere_revision && <Chip size="small" label="Por revisar" sx={{ height: 20, fontSize: 11.5, color: PALETA.avisoOscuro, bgcolor: PALETA.avisoFondo, border: `1px solid ${PALETA.avisoBorde}` }} />}
          {e.std_numero && <Typography variant="caption" color="text.secondary">STD {e.std_numero}</Typography>}
          {e.plazo && abierta && (
            <Typography variant="caption" sx={{ color: e.vencida ? PALETA.error : e.por_vencer ? PALETA.avisoOscuro : 'text.secondary', fontWeight: e.vencida || e.por_vencer ? 600 : 400 }}>
              · {textoPlazo(e.plazo, hoy)}
            </Typography>
          )}
          {e.responsable && <Typography variant="caption" color="text.secondary" noWrap>· {e.responsable}</Typography>}
          {e.campana && <Chip size="small" variant="outlined" label={e.campana} sx={{ height: 20, fontSize: 11.5, maxWidth: 160 }} />}
        </Box>
      </Box>
    </ButtonBase>
  )
}

export default function Entradas() {
  const tema = useTheme()
  const ancha = useMediaQuery(tema.breakpoints.up('md'))
  const muyAncha = useMediaQuery('(min-width:1440px)')
  const [consulta, setConsulta] = useSearchParams()
  const [lista, setLista] = useState<Entrada[] | null>(null)
  const [total, setTotal] = useState(0)
  const [equipo, setEquipo] = useState<MiembroEquipo[]>([])
  const [campanas, setCampanas] = useState<{ campana: string; total: number; abiertas: number }[]>([])
  const [q, setQ] = useState('')
  const [aviso, setAviso] = useState<Aviso | null>(null)
  const [soltados, setSoltados] = useState<File[]>([])
  const [subiendo, setSubiendo] = useState(false)
  // Entrada doble (fase 9.5): el pegado que acompaña a la subida (abrir la caja, o el texto del chat).
  const [pegado, setPegado] = useState<PegadoEnSubida | null>(null)
  const [anclaNuevo, setAnclaNuevo] = useState<HTMLElement | null>(null)
  const [encima, setEncima] = useState(false)
  // En escritorio la página ocupa justo la ventana (lista, ficha y PDF con su propio desplazamiento):
  // su alto es la ventana menos lo que queda arriba (barra y opciones del módulo), medido.
  const raiz = useRef<HTMLDivElement | null>(null)
  const [arriba, setArriba] = useState(90)
  useLayoutEffect(() => {
    const medir = () => raiz.current && setArriba(Math.max(0, Math.round(raiz.current.getBoundingClientRect().top + window.scrollY)))
    medir()
    window.addEventListener('resize', medir)
    return () => window.removeEventListener('resize', medir)
  }, [ancha])
  const rol = localStorage.getItem('qillqa_rol') ?? ''
  const soloLectura = rol === 'invitado'

  const ver = Number(consulta.get('ver') ?? '') || null
  const estado = consulta.get('estado') ?? ''
  const atencion = consulta.get('atencion') ?? ''
  const responsable = consulta.get('responsable') ?? ''
  const vencidas = consulta.get('vencidas') === '1'
  const campana = consulta.get('campana') ?? ''
  // Mesa de partes virtual (2026-10-12): `?via=mesa_virtual` deja solo lo que llegó por la página pública.
  const via = consulta.get('via') ?? ''

  const poner = (clave: string, valor: string) => {
    const c = new URLSearchParams(consulta)
    if (valor) c.set(clave, valor)
    else c.delete(clave)
    setConsulta(c, { replace: clave !== 'ver' })
  }

  const cargar = useCallback(async () => {
    const p = new URLSearchParams()
    if (q.trim()) p.set('q', q.trim())
    if (estado) p.set('estado', estado)
    if (atencion) p.set('atencion', atencion)
    if (responsable) p.set('responsable', responsable)
    if (vencidas) p.set('vencidas', 'true')
    if (campana) p.set('campana', campana)
    if (via) p.set('via', via)
    try {
      const r = await api<{ total: number; items: Entrada[] }>(`/api/entradas?${p}`)
      setLista(r.items)
      setTotal(r.total)
    } catch (e) {
      setLista([])
      setAviso({ tipo: 'error', texto: e instanceof Error ? e.message : 'No se pudo cargar la bandeja.' })
    }
  }, [q, estado, atencion, responsable, vencidas, campana, via])

  useEffect(() => {
    const t = setTimeout(() => void cargar(), q ? 300 : 0)
    return () => clearTimeout(t)
  }, [cargar, q])
  useEffect(() => {
    api<MiembroEquipo[]>('/api/admin/equipo').then(setEquipo).catch(() => setEquipo([]))
    api<{ campana: string; total: number; abiertas: number }[]>('/api/entradas/campanas').then(setCampanas).catch(() => {})
  }, [])
  // «Registrar recibidos» desde el menú (`?subir=1`); con `&pegar=<id>` (chat) se trae el texto
  // del mensaje y la primera ficha se llena con él.
  useEffect(() => {
    if (consulta.get('subir') !== '1' || soloLectura) return
    const mid = Number(consulta.get('pegar') ?? '')
    const c = new URLSearchParams(consulta)
    c.delete('subir')
    c.delete('pegar')
    setConsulta(c, { replace: true })
    setSoltados([])
    if (mid) {
      textoDeMensaje(mid)
        .then((texto) => { setPegado({ abrir: true, texto }); setSubiendo(true) })
        .catch(() => { setAviso({ tipo: 'error', texto: 'No se pudo traer el mensaje del chat; pegue el texto a mano.' }); setPegado({ abrir: true }); setSubiendo(true) })
    } else {
      setPegado(null)
      setSubiendo(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [consulta])

  const refrescar = () => {
    void cargar()
    api<{ campana: string; total: number; abiertas: number }[]>('/api/entradas/campanas').then(setCampanas).catch(() => {})
  }
  const nombresCampanas = useMemo(() => campanas.map((c) => c.campana), [campanas])
  const hoy = hoyIso()
  const avisar = (tipo: Aviso['tipo'], texto: string) => setAviso({ tipo, texto })
  const abrirSubida = (archivos: File[], conPegado: PegadoEnSubida | null = null) => {
    if (soloLectura) return
    setSoltados(archivos)
    setPegado(conPegado)
    setSubiendo(true)
  }

  const filtros = (
    <Box sx={{ px: { xs: 1.5, sm: 2 }, py: 1.25, borderBottom: '1px solid', borderColor: 'divider', bgcolor: 'background.paper' }}>
      {/* La acción principal en su sitio común (BarraModulo): primera, a la izquierda. */}
      <BarraModulo
        alActualizar={cargar}
        mb={0}
        principal={!soloLectura && (
          <Button variant="contained" startIcon={<UploadFileOutlinedIcon />} onClick={(e) => setAnclaNuevo(e.currentTarget)} sx={{ whiteSpace: 'nowrap' }}>
            Registrar documentos
          </Button>
        )}
      >
        <TextField
          size="small" placeholder="Buscar: remitente, asunto, n.º STD, texto…" value={q} onChange={(e) => setQ(e.target.value)}
          InputProps={{ startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> }}
          sx={{ flex: '1 1 240px', minWidth: 0 }}
        />
        <TextField size="small" select label="Estado" value={estado} onChange={(e) => poner('estado', e.target.value)} sx={{ minWidth: 150, flex: { xs: '1 1 140px', sm: '0 0 auto' } }}>
          <MenuItem value="">Sin archivadas</MenuItem>
          <MenuItem value="abiertas">Por atender</MenuItem>
          {ESTADOS.map((s) => <MenuItem key={s.v} value={s.v}>{s.t}</MenuItem>)}
          <MenuItem value="todas">Todas</MenuItem>
        </TextField>
        <TextField size="small" select label="Atención" value={atencion} onChange={(e) => poner('atencion', e.target.value)} sx={{ minWidth: 150, flex: { xs: '1 1 140px', sm: '0 0 auto' } }}>
          <MenuItem value="">Todas</MenuItem>
          {ATENCIONES.map((a) => <MenuItem key={a.v} value={a.v}>{a.t}</MenuItem>)}
        </TextField>
        <TextField size="small" select label="Responsable" value={responsable} onChange={(e) => poner('responsable', e.target.value)} sx={{ minWidth: 160, flex: { xs: '1 1 140px', sm: '0 0 auto' } }}>
          <MenuItem value="">Todos</MenuItem>
          <MenuItem value="yo">A mi cargo</MenuItem>
          <MenuItem value="sin">Sin responsable</MenuItem>
          {equipo.map((m) => <MenuItem key={m.id} value={String(m.id)}>{m.nombre_completo}</MenuItem>)}
        </TextField>
        {campanas.length > 0 && (
          <TextField size="small" select label="Campaña" value={campana} onChange={(e) => poner('campana', e.target.value)} sx={{ minWidth: 160, flex: { xs: '1 1 140px', sm: '0 0 auto' } }}>
            <MenuItem value="">Todas</MenuItem>
            {campanas.map((c) => <MenuItem key={c.campana} value={c.campana}>{c.campana} ({c.total})</MenuItem>)}
          </TextField>
        )}
        <FormControlLabel
          control={<Switch size="small" checked={vencidas} onChange={(e) => poner('vencidas', e.target.checked ? '1' : '')} />}
          label={<Typography variant="body2">Vencidas</Typography>}
          sx={{ ml: 0.25, mr: 0 }}
        />
        <FormControlLabel
          control={<Switch size="small" checked={via === 'mesa_virtual'} onChange={(e) => poner('via', e.target.checked ? 'mesa_virtual' : '')} />}
          label={<Typography variant="body2">Mesa virtual</Typography>}
          sx={{ ml: 0.25, mr: 0 }}
        />
      </BarraModulo>
    </Box>
  )

  const listaVista = (
    <Box sx={{ overflow: 'auto', minHeight: 0, flex: 1, bgcolor: 'background.paper' }}>
      {lista === null && <LinearProgress />}
      {lista && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', px: 2, py: 0.75, borderBottom: '1px solid', borderColor: 'divider' }}>
          {total} documento(s){campana ? ` en «${campana}»` : ''}
        </Typography>
      )}
      {lista?.map((e) => (
        <FilaEntrada key={e.id} e={e} hoy={hoy} activa={e.id === ver} alElegir={() => poner('ver', String(e.id))} />
      ))}
      {lista?.length === 0 && (
        <Box sx={{ p: 3, textAlign: 'center' }}>
          <MoveToInboxOutlinedIcon sx={{ fontSize: 40, color: PALETA.apagado }} />
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            No hay documentos recibidos con estos filtros.
          </Typography>
          {!soloLectura && <ZonaSoltar alElegir={abrirSubida} />}
        </Box>
      )}
    </Box>
  )

  const detalle = ver ? (
    <DetalleEntrada
      key={ver}
      id={ver}
      equipo={equipo}
      campanas={nombresCampanas}
      pdfAparte={muyAncha}
      soloLectura={soloLectura}
      alCambiar={refrescar}
      alCerrar={ancha ? undefined : () => poner('ver', '')}
      alAvisar={avisar}
    />
  ) : (
    <Box sx={{ p: 4, textAlign: 'center', color: 'text.secondary' }}>
      <MoveToInboxOutlinedIcon sx={{ fontSize: 44, color: PALETA.apagado }} />
      <Typography variant="body2">Elija un documento para ver su ficha.</Typography>
      {/* 2026-10-06: quitado «Para registrar nuevos, arrastre…» (repetido en la página). */}
    </Box>
  )

  const elegida = lista?.find((e) => e.id === ver)

  return (
    <Marco modulo="recibidos" fondo={PALETA.fondo}>
      <Box
        onDragOver={(e) => {
          if (soloLectura || !e.dataTransfer.types.includes('Files')) return
          e.preventDefault()
          setEncima(true)
        }}
        onDragLeave={(e) => {
          if (e.currentTarget === e.target) setEncima(false)
        }}
        onDrop={(e) => {
          if (soloLectura) return
          e.preventDefault()
          setEncima(false)
          const pdfs = Array.from(e.dataTransfer.files).filter((f) => ADMITIDOS.test(f.name))
          if (pdfs.length) abrirSubida(pdfs)
          else avisar('error', 'Solo se registran PDF, Word o imágenes.')
        }}
        ref={raiz}
        sx={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, position: 'relative', ...(ancha ? { height: `calc(100dvh - ${arriba}px)`, flex: 'none', overflow: 'hidden' } : {}) }}
      >
        {filtros}
        {encima && (
          <Box sx={{ position: 'absolute', inset: 8, zIndex: 5, border: '2px dashed', borderColor: 'primary.main', borderRadius: 2, bgcolor: `${PALETA.fondo}EB`, display: 'flex', alignItems: 'center', justifyContent: 'center', pointerEvents: 'none' }}>
            <Typography sx={{ fontWeight: 600, color: 'primary.main' }}>Suelte los PDF para leer sus fichas</Typography>
          </Box>
        )}
        {ancha ? (
          <Box sx={{ flex: 1, minHeight: 0, display: 'grid', gridTemplateRows: 'minmax(0, 1fr)', gridTemplateColumns: muyAncha && ver ? '400px minmax(0, 1fr) minmax(0, 1fr)' : '400px minmax(0, 1fr)' }}>
            <Box sx={{ display: 'flex', flexDirection: 'column', minHeight: 0, borderRight: '1px solid', borderColor: 'divider' }}>{listaVista}</Box>
            <Box sx={{ minHeight: 0, overflow: 'hidden', bgcolor: 'background.paper' }}>{detalle}</Box>
            {muyAncha && ver && (
              <Box sx={{ minHeight: 0, p: 1.5, borderLeft: '1px solid', borderColor: 'divider' }}>
                <VisorPdf ruta={`/api/entradas/${ver}/pdf`} alto="100%" nombre={elegida?.nombre_original || 'recibido.pdf'} />
              </Box>
            )}
          </Box>
        ) : (
          <>
            {listaVista}
            <Dialog fullScreen open={Boolean(ver)} onClose={() => poner('ver', '')}>
              {detalle}
            </Dialog>
          </>
        )}
      </Box>

      <ElegirEntrada
        ancla={anclaNuevo}
        alCerrar={() => setAnclaNuevo(null)}
        tipo="documento-recibido"
        etiquetaManual="Subir los PDF"
        alManual={() => abrirSubida([])}
        alPrompt={() => abrirSubida([], { abrir: true })}
      />
      <SubirEntradas
        abierto={subiendo}
        archivos={soltados}
        pegado={pegado}
        equipo={equipo}
        campanas={nombresCampanas}
        alCerrar={() => setSubiendo(false)}
        alTerminar={(creadas) => {
          refrescar()
          avisar('success', `${creadas.length} documento(s) recibido(s) registrado(s).`)
          if (creadas.length === 1) poner('ver', String(creadas[0]))
        }}
      />
      <Snackbar open={aviso !== null} autoHideDuration={5000} onClose={() => setAviso(null)} anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}>
        {aviso ? <Alert severity={aviso.tipo} variant="filled" onClose={() => setAviso(null)}>{aviso.texto}</Alert> : undefined}
      </Snackbar>
    </Marco>
  )
}

