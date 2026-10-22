/**
 * «Enviar un documento» (mesa de partes virtual, 2026-10-12): cuatro pasos cortos, pensados para el
 * celular — quién envía, el documento, los archivos, revisar y declarar — y el envío con su avance.
 * Al terminar, el cargo. Lo que se pide sigue a la Directiva 07-2022-DGP/CR (5.1 y 5.2) y al TUO de
 * la Ley 27444: persona natural con DNI o carné de extranjería, o entidad con RUC y representante;
 * tipo, número, folios y asunto; PDF principal y anexos; declaración jurada y datos personales.
 *
 * El servidor vuelve a validar todo; aquí se valida para avisar antes y en el campo que toca.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import TextField from '@mui/material/TextField'
import MenuItem from '@mui/material/MenuItem'
import Typography from '@mui/material/Typography'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import Checkbox from '@mui/material/Checkbox'
import FormControlLabel from '@mui/material/FormControlLabel'
import LinearProgress from '@mui/material/LinearProgress'
import Alert from '@mui/material/Alert'
import PersonOutlineIcon from '@mui/icons-material/PersonOutline'
import AccountBalanceOutlinedIcon from '@mui/icons-material/AccountBalanceOutlined'
import SendIcon from '@mui/icons-material/Send'
import { PALETA } from '@qillqa/tiqsi'
import ElegirArchivos, { PDF_O_IMAGEN, SOLO_PDF, motivoArchivo } from './ElegirArchivos'
import Cargo, { Fila } from './Cargo'
import { ErrorMesa, enviarConAvance, errorDoc as errorDocCrudo, fechaHora, leerConfig, peso, soloDoc, type ConfigPublica, type RespuestaTramite } from './modelo'

// El número se limpia (espacios, puntos, guiones) antes de validarlo, como en el servidor.
const errorDoc = (tipo: string, n: string) => errorDocCrudo(tipo, soloDoc(n))

type Datos = {
  tipo_persona: 'natural' | 'juridica'
  doc_tipo: 'DNI' | 'CE'
  doc_numero: string
  nombres: string
  apellidos: string
  razon_social: string
  representante: string
  representante_doc_tipo: 'DNI' | 'CE'
  representante_doc: string
  cargo: string
  telefono: string
  correo: string
  direccion: string
  tipo_documento: string
  numero_documento: string
  folios: string
  asunto: string
  referencia: string
  comentario: string
}

const VACIO: Datos = {
  tipo_persona: 'natural', doc_tipo: 'DNI', doc_numero: '', nombres: '', apellidos: '', razon_social: '', representante: '',
  representante_doc_tipo: 'DNI', representante_doc: '', cargo: '', telefono: '', correo: '', direccion: '',
  tipo_documento: '', numero_documento: '', folios: '', asunto: '', referencia: '', comentario: '',
}

const PASOS = ['Quién envía', 'El documento', 'Los archivos', 'Revisar y enviar']


/** Errores de un paso (campo → mensaje). */
function validar(paso: number, d: Datos, principal: File[], anexos: File[], cfg: ConfigPublica, declaro: boolean, autorizo: boolean): Record<string, string> {
  const e: Record<string, string> = {}
  if (paso === 0) {
    if (d.tipo_persona === 'natural') {
      if (errorDoc(d.doc_tipo, d.doc_numero)) e.doc_numero = errorDoc(d.doc_tipo, d.doc_numero)
      if (!d.nombres.trim()) e.nombres = 'Escriba sus nombres.'
      if (!d.apellidos.trim()) e.apellidos = 'Escriba sus apellidos.'
    } else {
      if (errorDoc('RUC', d.doc_numero)) e.doc_numero = errorDoc('RUC', d.doc_numero)
      if (!d.razon_social.trim()) e.razon_social = 'Escriba la razón social o el nombre de la entidad.'
      if (!d.representante.trim()) e.representante = 'Escriba quién firma o representa.'
      if (errorDoc(d.representante_doc_tipo, d.representante_doc)) e.representante_doc = errorDoc(d.representante_doc_tipo, d.representante_doc)
    }
    const tel = d.telefono.replace(/[^\d+]/g, '')
    if (tel && !/^\+?\d{6,15}$/.test(tel)) e.telefono = 'El número no parece válido.'
    if (d.correo.trim() && !/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(d.correo.trim())) e.correo = 'El correo no parece válido.'
    if (!tel && !d.correo.trim()) e.telefono = 'Deje un celular o un correo para comunicarnos con usted.'
  }
  if (paso === 1) {
    if (!d.tipo_documento) e.tipo_documento = 'Elija el tipo de documento.'
    if (!/^\d{1,4}$/.test(d.folios) || Number(d.folios) < 1) e.folios = 'Indique cuántas hojas tiene (1 o más).'
    if (d.asunto.trim().length < 5) e.asunto = 'Escriba el asunto: de qué trata su documento.'
  }
  if (paso === 2) {
    const max = cfg.max_archivo_mb ?? 20
    if (principal.length !== 1) e.principal = 'Adjunte su documento en PDF.'
    else if (motivoArchivo(principal[0], SOLO_PDF, max)) e.principal = `El archivo ${motivoArchivo(principal[0], SOLO_PDF, max)}.`
    const malo = anexos.find((f) => motivoArchivo(f, PDF_O_IMAGEN, max))
    if (malo) e.anexos = `«${malo.name}» ${motivoArchivo(malo, PDF_O_IMAGEN, max)}.`
    const total = [...principal, ...anexos].reduce((s, f) => s + f.size, 0)
    if (total > (cfg.max_total_mb ?? 30) * 1024 * 1024) e.anexos = `Entre todos pasan de ${cfg.max_total_mb} MB (llevan ${peso(total)}).`
  }
  if (paso === 3 && (!declaro || !autorizo)) e.declaracion = 'Marque las dos casillas para enviar.'
  return e
}

export default function FormularioEnvio({ cfg: cfgInicial, alSeguir }: { cfg: ConfigPublica; alSeguir: (r: RespuestaTramite) => void }) {
  const [cfg, setCfg] = useState(cfgInicial)
  const [paso, setPaso] = useState(0)
  const [d, setD] = useState<Datos>({ ...VACIO, tipo_documento: '' })
  const [principal, setPrincipal] = useState<File[]>([])
  const [anexos, setAnexos] = useState<File[]>([])
  const [declaro, setDeclaro] = useState(false)
  const [autorizo, setAutorizo] = useState(false)
  const [errores, setErrores] = useState<Record<string, string>>({})
  const [avance, setAvance] = useState<number | null>(null)
  const [fallo, setFallo] = useState('')
  const [hecho, setHecho] = useState<RespuestaTramite | null>(null)
  const trampa = useRef<HTMLInputElement | null>(null)
  const arriba = useRef<HTMLDivElement | null>(null)
  const abierto = useRef(Date.now())

  useEffect(() => {
    arriba.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [paso, hecho])

  const poner = (c: Partial<Datos>) => {
    setD((x) => ({ ...x, ...c }))
    setErrores((x) => {
      const y = { ...x }
      Object.keys(c).forEach((k) => delete y[k])
      return y
    })
  }
  const campo = (k: keyof Datos) => ({
    value: d[k],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => poner({ [k]: e.target.value } as Partial<Datos>),
    error: Boolean(errores[k]),
    helperText: errores[k] || undefined,
    fullWidth: true,
    name: k,
  })

  const seguir = () => {
    const e = validar(paso, d, principal, anexos, cfg, declaro, autorizo)
    setErrores(e)
    if (Object.keys(e).length === 0) setPaso(paso + 1)
  }

  const enviar = async (reintento = false) => {
    const e = validar(3, d, principal, anexos, cfg, declaro, autorizo)
    setErrores(e)
    if (Object.keys(e).length) return
    setFallo('')
    let ficha = cfg.ficha ?? ''
    // La ficha del formulario vale 24 h: si la página lleva más tiempo abierta, se pide otra.
    if (reintento || Date.now() - abierto.current > 20 * 3600 * 1000) {
      const nueva = await leerConfig().catch(() => null)
      if (nueva?.ficha) {
        setCfg(nueva)
        ficha = nueva.ficha
        abierto.current = Date.now()
      }
    }
    const f = new FormData()
    Object.entries(d).forEach(([k, v]) => f.append(k, k === 'doc_numero' || k === 'representante_doc' ? soloDoc(v) : String(v).trim()))
    f.append('ficha', ficha)
    f.append('sitio_web', trampa.current?.value ?? '')
    f.append('declaracion', declaro ? 'si' : '')
    f.append('datos_personales', autorizo ? 'si' : '')
    f.append('principal', principal[0])
    anexos.forEach((a) => f.append('anexos', a))
    setAvance(0)
    try {
      const r = await enviarConAvance('/enviar', f, setAvance)
      setHecho(r)
    } catch (x) {
      if (x instanceof ErrorMesa && x.campo === 'ficha' && !reintento) {
        await new Promise((ok) => setTimeout(ok, 3200))
        setAvance(null)
        return enviar(true)
      }
      const m = x instanceof Error ? x.message : 'No se pudo enviar.'
      setFallo(m)
      if (x instanceof ErrorMesa && x.campo) {
        const aPaso: Record<string, number> = { doc_numero: 0, nombres: 0, apellidos: 0, razon_social: 0, representante: 0, representante_doc: 0, telefono: 0, correo: 0, tipo_persona: 0, doc_tipo: 0,
          tipo_documento: 1, folios: 1, asunto: 1, principal: 2, anexos: 2, declaracion: 3 }
        if (x.campo in aPaso) {
          setErrores({ [x.campo]: m })
          setPaso(aPaso[x.campo])
        }
      }
    } finally {
      setAvance(null)
    }
  }

  const resumenRemitente = useMemo(() => d.tipo_persona === 'natural'
    ? `${d.nombres} ${d.apellidos} · ${d.doc_tipo} ${soloDoc(d.doc_numero)}`
    : `${d.razon_social} · RUC ${soloDoc(d.doc_numero)} · ${d.representante}${d.cargo ? ` (${d.cargo})` : ''}`, [d])

  if (hecho) return <div ref={arriba}><Cargo tramite={hecho.tramite} acceso={hecho.acceso} alSeguir={() => alSeguir(hecho)} /></div>

  const enviando = avance !== null
  return (
    <Box ref={arriba} component="form" noValidate onSubmit={(e) => { e.preventDefault(); if (paso < 3) seguir(); else void enviar() }}>
      {/* Campo trampa: invisible para las personas (y para los lectores de pantalla); un robot lo llena. */}
      <Box aria-hidden="true" sx={{ position: 'absolute', left: '-10000px', width: 1, height: 1, overflow: 'hidden' }}>
        <label>Sitio web<input ref={trampa} type="text" name="sitio_web" tabIndex={-1} autoComplete="off" defaultValue="" /></label>
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>Paso {paso + 1} de {PASOS.length}</Typography>
      <Typography component="h2" sx={{ fontWeight: 700, fontSize: 18, mb: 0.5 }}>{PASOS[paso]}</Typography>
      <LinearProgress variant="determinate" value={((paso + 1) / PASOS.length) * 100} sx={{ mb: 2, height: 4, borderRadius: 2 }} aria-hidden />

      {paso === 0 && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.75 }}>
          <ToggleButtonGroup exclusive fullWidth value={d.tipo_persona} onChange={(_, v) => v && poner({ tipo_persona: v, doc_numero: '' })} aria-label="Envía como">
            <ToggleButton value="natural" sx={{ gap: 0.75, py: 1.1 }}><PersonOutlineIcon fontSize="small" />Persona</ToggleButton>
            <ToggleButton value="juridica" sx={{ gap: 0.75, py: 1.1 }}><AccountBalanceOutlinedIcon fontSize="small" />Entidad o empresa</ToggleButton>
          </ToggleButtonGroup>
          {d.tipo_persona === 'natural' ? (
            <>
              <Box sx={{ display: 'flex', gap: 1 }}>
                <TextField select label="Documento" value={d.doc_tipo} onChange={(e) => poner({ doc_tipo: e.target.value as Datos['doc_tipo'] })} sx={{ width: 130, flexShrink: 0 }}>
                  <MenuItem value="DNI">DNI</MenuItem>
                  <MenuItem value="CE">Carné de extranjería</MenuItem>
                </TextField>
                <TextField label="Número" required inputProps={{ inputMode: d.doc_tipo === 'DNI' ? 'numeric' : 'text', maxLength: 12, autoComplete: 'off' }} {...campo('doc_numero')} />
              </Box>
              <TextField label="Nombres" required inputProps={{ autoComplete: 'given-name', maxLength: 100 }} {...campo('nombres')} />
              <TextField label="Apellidos" required inputProps={{ autoComplete: 'family-name', maxLength: 100 }} {...campo('apellidos')} />
            </>
          ) : (
            <>
              <TextField label="RUC" required inputProps={{ inputMode: 'numeric', maxLength: 11, autoComplete: 'off' }} {...campo('doc_numero')} />
              <TextField label="Razón social o nombre de la entidad" required inputProps={{ autoComplete: 'organization', maxLength: 300 }} {...campo('razon_social')} />
              <TextField label="Quien firma o representa" required inputProps={{ autoComplete: 'name', maxLength: 200 }} {...campo('representante')} />
              <Box sx={{ display: 'flex', gap: 1 }}>
                <TextField select label="Su documento" value={d.representante_doc_tipo} onChange={(e) => poner({ representante_doc_tipo: e.target.value as Datos['representante_doc_tipo'] })} sx={{ width: 130, flexShrink: 0 }}>
                  <MenuItem value="DNI">DNI</MenuItem>
                  <MenuItem value="CE">Carné de extranjería</MenuItem>
                </TextField>
                <TextField label="Número" required inputProps={{ inputMode: 'numeric', maxLength: 12, autoComplete: 'off' }} {...campo('representante_doc')} />
              </Box>
              <TextField label="Cargo (opcional)" inputProps={{ autoComplete: 'organization-title', maxLength: 200 }} {...campo('cargo')} />
            </>
          )}
          <TextField label="Celular" type="tel" inputProps={{ inputMode: 'tel', autoComplete: 'tel', maxLength: 20 }} {...campo('telefono')}
            helperText={errores.telefono || 'Celular o correo: al menos uno, para comunicarnos con usted.'} />
          <TextField label="Correo (opcional)" type="email" inputProps={{ autoComplete: 'email', maxLength: 200 }} {...campo('correo')} />
          <TextField label="Dirección (opcional)" inputProps={{ autoComplete: 'street-address', maxLength: 300 }} {...campo('direccion')} />
        </Box>
      )}

      {paso === 1 && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.75 }}>
          <TextField select label="Tipo de documento" required {...campo('tipo_documento')} onChange={(e) => poner({ tipo_documento: e.target.value })}>
            {(cfg.tipos ?? []).map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
          </TextField>
          <Box sx={{ display: 'flex', gap: 1 }}>
            <TextField label="Número (opcional)" placeholder="001-2026" inputProps={{ maxLength: 120 }} {...campo('numero_documento')} />
            <TextField label="Folios" required inputProps={{ inputMode: 'numeric', maxLength: 4 }} {...campo('folios')} sx={{ width: 110, flexShrink: 0 }}
              onChange={(e) => poner({ folios: e.target.value.replace(/\D/g, '') })} />
          </Box>
          <TextField label="Asunto" required multiline minRows={2} inputProps={{ maxLength: 600 }} placeholder="De qué trata su documento" {...campo('asunto')} />
          <TextField label="Responde a un documento del despacho (opcional)" placeholder="Por ejemplo: Oficio N.° 61-2026" inputProps={{ maxLength: 300 }} {...campo('referencia')} />
          <TextField label="Comentario (opcional)" multiline minRows={2} inputProps={{ maxLength: 2000 }} {...campo('comentario')} />
        </Box>
      )}

      {paso === 2 && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <Box>
            <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>Documento principal (PDF)</Typography>
            <ElegirArchivos id="principal" etiqueta="Elegir el PDF" archivos={principal} alCambiar={(a) => { setPrincipal(a); setErrores({}); setFallo('') }}
              maxMb={cfg.max_archivo_mb ?? 20} error={errores.principal} />
          </Box>
          {(cfg.max_anexos ?? 0) > 0 && (
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>Anexos (opcional)</Typography>
              <ElegirArchivos id="anexos" etiqueta={`Agregar anexos (hasta ${cfg.max_anexos})`} archivos={anexos} alCambiar={(a) => { setAnexos(a); setErrores({}); setFallo('') }}
                multiple maximo={cfg.max_anexos} admitidos={PDF_O_IMAGEN} maxMb={cfg.max_archivo_mb ?? 20} error={errores.anexos} />
            </Box>
          )}
          <Typography variant="caption" color="text.secondary" id="principal-ayuda">
            PDF para el documento; PDF, JPG o PNG para los anexos. Hasta {cfg.max_archivo_mb} MB por archivo y {cfg.max_total_mb} MB en total.
          </Typography>
        </Box>
      )}

      {paso === 3 && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
          <Box sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1.5, p: 1.5, bgcolor: 'background.paper' }}>
            <Fila rotulo="Remitente">{resumenRemitente}</Fila>
            <Fila rotulo="Contacto">{[d.telefono, d.correo].filter(Boolean).join(' · ')}</Fila>
            <Fila rotulo="Documento">{[d.tipo_documento, d.numero_documento].filter(Boolean).join(' ')} · {d.folios} folio(s)</Fila>
            <Fila rotulo="Asunto">{d.asunto}</Fila>
            <Fila rotulo="Archivos">{[...principal, ...anexos].map((f) => `${f.name} (${peso(f.size)})`).join(' · ')}</Fila>
          </Box>
          {cfg.presentado_si_envia && cfg.fuera_de_horario && (
            <Alert severity="info" variant="outlined">
              Ahora está fuera del horario de atención: si envía, se tendrá por presentado el {fechaHora(cfg.presentado_si_envia)}.
            </Alert>
          )}
          <FormControlLabel
            control={<Checkbox checked={declaro} onChange={(e) => { setDeclaro(e.target.checked); setErrores({}) }} />}
            label={<Typography variant="body2">Declaro bajo juramento que los datos y los documentos que presento son verdaderos.</Typography>}
            sx={{ alignItems: 'flex-start', '& .MuiCheckbox-root': { pt: 0.25 } }}
          />
          <FormControlLabel
            control={<Checkbox checked={autorizo} onChange={(e) => { setAutorizo(e.target.checked); setErrores({}) }} />}
            label={
              <Typography variant="body2">
                Autorizo que el despacho use mis datos personales para atender este trámite y para mantener contacto conmigo (Ley 29733, de Protección de Datos Personales). Puedo pedir acceder a ellos, corregirlos o suprimirlos.
              </Typography>
            }
            sx={{ alignItems: 'flex-start', '& .MuiCheckbox-root': { pt: 0.25 } }}
          />
          <Typography variant="caption" color="text.secondary" sx={{ pl: 4 }}>
            Por seguridad, esta página registra la conexión (IP y navegador) de cada envío y consulta; ese registro se conserva por el plazo que fija la ley.
          </Typography>
          {errores.declaracion && <Typography variant="caption" color="error" role="alert">{errores.declaracion}</Typography>}
        </Box>
      )}

      {fallo && <Alert severity="error" sx={{ mt: 2 }} role="alert">{fallo}</Alert>}
      {enviando && (
        <Box sx={{ mt: 2 }} aria-live="polite">
          <LinearProgress variant={avance! < 1 ? 'determinate' : 'indeterminate'} value={avance! * 100} />
          <Typography variant="caption" color="text.secondary">{avance! < 1 ? `Subiendo… ${Math.round(avance! * 100)} %` : 'Registrando y preparando su cargo…'}</Typography>
        </Box>
      )}
      <Box sx={{ display: 'flex', gap: 1, mt: 2.5 }}>
        {paso > 0 && <Button onClick={() => { setErrores({}); setPaso(paso - 1) }} disabled={enviando} sx={{ flex: { xs: 1, sm: '0 0 auto' } }}>Atrás</Button>}
        <Box sx={{ flex: 1, display: { xs: 'none', sm: 'block' } }} />
        {paso < 3 ? (
          <Button type="submit" variant="contained" sx={{ flex: { xs: 2, sm: '0 0 auto' }, py: 1.1 }}>Continuar</Button>
        ) : (
          <Button type="submit" variant="contained" startIcon={<SendIcon />} disabled={enviando} sx={{ flex: { xs: 2, sm: '0 0 auto' }, py: 1.1, bgcolor: PALETA.guinda }}>
            Enviar
          </Button>
        )}
      </Box>
    </Box>
  )
}
