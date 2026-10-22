/**
 * MESA DE PARTES VIRTUAL — página PÚBLICA, sin iniciar sesión (Edison 2026-10-12: «que el agente
 * exterior pueda manejarla fácil, sin registrarse ni nada»). backend/app/api/mesa_publica.py.
 *
 *   /mesa-de-partes              dos opciones grandes: «Enviar un documento» y «Seguir mi trámite»
 *   /mesa-de-partes/enviar       el formulario por pasos y, al terminar, el cargo
 *   /mesa-de-partes/seguimiento  código + documento → estado, observación, subsanación y respuesta
 *
 * No lleva `Marco` (no hay sesión ni menú del sistema), pero sí el mismo tema y la misma paleta. El
 * nombre del despacho sale del entorno (VITE_NOMBRE_DESPACHO, el mismo del login) o del que fijó
 * Administración; nada del despacho en el código. Primero el celular: una columna de 640 px como
 * mucho, campos de 16 px, botones al ancho.
 */
import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useSearchParams } from 'react-router'
import Box from '@mui/material/Box'
import ButtonBase from '@mui/material/ButtonBase'
import Typography from '@mui/material/Typography'
import LinearProgress from '@mui/material/LinearProgress'
import Alert from '@mui/material/Alert'
import Link from '@mui/material/Link'
import GlobalStyles from '@mui/material/GlobalStyles'
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined'
import ManageSearchOutlinedIcon from '@mui/icons-material/ManageSearchOutlined'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import { PALETA } from '@qillqa/tiqsi'
import FormularioEnvio from '../componentes/mesa/FormularioEnvio'
import Seguimiento from '../componentes/mesa/Seguimiento'
import { leerConfig, textoHorario, type ConfigPublica, type RespuestaTramite } from '../componentes/mesa/modelo'

const RAIZ = '/mesa-de-partes'

function Opcion({ icono, titulo, texto, alElegir }: { icono: React.ReactNode; titulo: string; texto: string; alElegir: () => void }) {
  return (
    <ButtonBase
      onClick={alElegir}
      sx={{
        display: 'flex', alignItems: 'center', gap: 1.75, width: '100%', textAlign: 'left', p: { xs: 2, sm: 2.5 },
        border: '1px solid', borderColor: 'divider', borderRadius: 2, bgcolor: 'background.paper',
        transition: 'border-color .15s, box-shadow .15s',
        '&:hover, &:focus-visible': { borderColor: PALETA.guinda, boxShadow: `0 0 0 3px ${PALETA.guindaSuave}` },
      }}
    >
      <Box sx={{ width: 52, height: 52, borderRadius: 2, flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', bgcolor: PALETA.guindaSuave, color: PALETA.guinda }}>
        {icono}
      </Box>
      <Box sx={{ minWidth: 0, flex: 1 }}>
        <Typography sx={{ fontWeight: 700, fontSize: { xs: 17, sm: 18 } }}>{titulo}</Typography>
        <Typography variant="body2" color="text.secondary">{texto}</Typography>
      </Box>
      <ChevronRightIcon sx={{ color: PALETA.textoTenue }} />
    </ButtonBase>
  )
}

export default function MesaVirtual() {
  const ubicacion = useLocation()
  const navegar = useNavigate()
  const [consulta] = useSearchParams()
  const [cfg, setCfg] = useState<ConfigPublica | null>(null)
  const [fallo, setFallo] = useState('')
  // Lo recién enviado pasa al seguimiento sin volver a escribir el código (solo en memoria).
  const [recien, setRecien] = useState<RespuestaTramite | null>(null)
  const vista = ubicacion.pathname.replace(/\/+$/, '') === `${RAIZ}/enviar` ? 'enviar' : ubicacion.pathname.startsWith(`${RAIZ}/seguimiento`) ? 'seguimiento' : 'inicio'

  useEffect(() => {
    document.title = `Mesa de partes virtual${cfg?.receptor ? ` · ${cfg.receptor}` : ''}`
  }, [cfg])
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [vista])
  useEffect(() => {
    leerConfig().then(setCfg).catch((e) => setFallo(e instanceof Error ? e.message : 'No se pudo abrir la mesa de partes.'))
  }, [])

  const nombre = cfg?.receptor || (import.meta.env.VITE_NOMBRE_DESPACHO as string | undefined) || 'Despacho parlamentario'
  const ir = (a: string) => navegar(a)

  return (
    <Box sx={{ minHeight: '100dvh', bgcolor: PALETA.fondo, display: 'flex', flexDirection: 'column' }}>
      {/* Al imprimir el cargo, solo el cargo. */}
      <GlobalStyles styles={{ '@media print': { '.no-imprimir, header, footer': { display: 'none !important' }, body: { background: '#fff' }, '#cargo': { border: 'none !important' } } }} />
      <Box component="header" sx={{ bgcolor: 'background.paper', color: 'text.primary', borderBottom: '1px solid', borderColor: 'divider', px: 2, py: { xs: 1.5, sm: 2 } }}>
        <Box sx={{ maxWidth: 640, mx: 'auto', display: 'flex', alignItems: 'center', gap: 1 }}>
          {vista !== 'inicio' && (
            <ButtonBase onClick={() => ir(RAIZ)} aria-label="Volver al inicio de la mesa de partes" sx={{ borderRadius: 1, p: 0.5, ml: -0.5 }}>
              <ArrowBackIcon />
            </ButtonBase>
          )}
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontSize: 12.5, color: 'text.secondary', lineHeight: 1.2 }} noWrap>{nombre}</Typography>
            <Typography component="h1" sx={{ fontWeight: 700, fontSize: { xs: 18, sm: 20 }, lineHeight: 1.25 }}>Mesa de partes virtual</Typography>
          </Box>
        </Box>
      </Box>

      <Box component="main" sx={{ flex: 1, width: '100%', maxWidth: 640, mx: 'auto', px: 2, py: { xs: 2, sm: 3 } }}>
        {!cfg && !fallo && <LinearProgress />}
        {fallo && <Alert severity="error">{fallo}</Alert>}
        {cfg && !cfg.activa && vista !== 'seguimiento' && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            <Alert severity="info" variant="outlined">{cfg.mensaje ?? 'La mesa de partes virtual no está recibiendo documentos en este momento.'}</Alert>
            {/* Quien ya presentó sigue pudiendo ver su trámite. */}
            <Opcion icono={<ManageSearchOutlinedIcon sx={{ fontSize: 28 }} />} titulo="Seguir mi trámite"
              texto="Con su código de seguimiento y su documento de identidad." alElegir={() => ir(`${RAIZ}/seguimiento`)} />
          </Box>
        )}
        {cfg?.activa && vista === 'inicio' && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            {cfg.presentacion && <Typography variant="body1" sx={{ mb: 0.5 }}>{cfg.presentacion}</Typography>}
            <Opcion icono={<UploadFileOutlinedIcon sx={{ fontSize: 28 }} />} titulo="Enviar un documento"
              texto="Llene sus datos y suba su PDF. Recibe su cargo al instante." alElegir={() => ir(`${RAIZ}/enviar`)} />
            <Opcion icono={<ManageSearchOutlinedIcon sx={{ fontSize: 28 }} />} titulo="Seguir mi trámite"
              texto="Con su código de seguimiento y su documento de identidad." alElegir={() => ir(`${RAIZ}/seguimiento`)} />
            <Box sx={{ mt: 1.5, display: 'flex', flexDirection: 'column', gap: 0.75 }}>
              <Typography variant="subtitle2">Antes de empezar</Typography>
              <Typography variant="body2" color="text.secondary">
                · Tenga a mano su DNI o carné de extranjería; si envía por una entidad, su RUC.
              </Typography>
              <Typography variant="body2" color="text.secondary">
                · El documento en PDF (hasta {cfg.max_archivo_mb} MB); anexos en PDF, JPG o PNG (hasta {cfg.max_anexos}).
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {cfg.horario?.continua
                  ? '· Atendemos las 24 horas, todos los días: su documento queda presentado el día y la hora en que llega. Los plazos se cuentan en días hábiles.'
                  : `· Recibimos a toda hora. Atendemos ${textoHorario(cfg.horario)}: lo que llega fuera de ese horario se tiene por presentado el día hábil siguiente.`}
              </Typography>
            </Box>
          </Box>
        )}
        {cfg?.activa && vista === 'enviar' && (
          <FormularioEnvio cfg={cfg} alSeguir={(r) => { setRecien(r); ir(`${RAIZ}/seguimiento`) }} />
        )}
        {cfg && vista === 'seguimiento' && (
          <Seguimiento inicial={recien} codigoInicial={(consulta.get('codigo') ?? '').toUpperCase().slice(0, 20)} />
        )}
      </Box>

      <Box component="footer" sx={{ px: 2, py: 2, borderTop: '1px solid', borderColor: 'divider', bgcolor: 'background.paper' }}>
        <Box sx={{ maxWidth: 640, mx: 'auto' }}>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            {nombre} · Mesa de partes virtual{cfg?.horario ? ` · Atención: ${textoHorario(cfg.horario)}` : ''}
          </Typography>
          {vista !== 'inicio' && <Link component="button" variant="caption" onClick={() => ir(RAIZ)}>Volver al inicio</Link>}
        </Box>
      </Box>
    </Box>
  )
}
