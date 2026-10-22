/**
 * El CARGO DE RECEPCIÓN en pantalla (2026-10-12): expediente, código de seguimiento, fecha y hora,
 * desde cuándo se tiene por presentado, el resumen y la huella de cada archivo (TUO de la Ley
 * 27444, arts. 117.2 y 124.2). Se descarga en PDF (lo arma el servidor), se imprime o se copia el
 * código. No hay correo: lo dice claro para que nadie espere uno.
 */
import { useState } from 'react'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Typography from '@mui/material/Typography'
import Alert from '@mui/material/Alert'
import Divider from '@mui/material/Divider'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import DownloadIcon from '@mui/icons-material/Download'
import PrintOutlinedIcon from '@mui/icons-material/PrintOutlined'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import SearchIcon from '@mui/icons-material/Search'
import { PALETA } from '@qillqa/tiqsi'
import { CLASE_ARCHIVO, copiarTexto, descargar, fechaHora, peso, presentadoOtroDia, type Tramite } from './modelo'

export function Fila({ rotulo, children, mono = false }: { rotulo: string; children: React.ReactNode; mono?: boolean }) {
  return (
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '170px 1fr' }, gap: { xs: 0, sm: 1.5 }, py: 0.6 }}>
      <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600, pt: { sm: 0.25 } }}>{rotulo}</Typography>
      <Typography variant="body2" component="div" sx={{ wordBreak: 'break-word', ...(mono ? { fontFamily: 'ui-monospace, Consolas, monospace', fontSize: 12.5 } : {}) }}>
        {children}
      </Typography>
    </Box>
  )
}

export default function Cargo({ tramite, acceso, alSeguir }: { tramite: Tramite; acceso: string; alSeguir: () => void }) {
  const [aviso, setAviso] = useState<{ tipo: 'success' | 'error'; texto: string } | null>(null)
  const t = tramite
  const copiar = async () => {
    const ok = await copiarTexto(t.codigo)
    setAviso(ok ? { tipo: 'success', texto: 'Código copiado.' } : { tipo: 'error', texto: 'No se pudo copiar: anótelo a mano.' })
  }
  const bajar = async () => {
    try {
      await descargar('/cargo', acceso, `Cargo-${t.expediente}.pdf`)
    } catch (e) {
      setAviso({ tipo: 'error', texto: e instanceof Error ? e.message : 'No se pudo descargar el cargo.' })
    }
  }
  return (
    <Box>
      <Box className="no-imprimir" sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5, color: PALETA.exito }}>
        <CheckCircleOutlineIcon />
        <Typography component="h2" sx={{ fontWeight: 700, fontSize: 18 }}>Documento recibido</Typography>
      </Box>
      <Box id="cargo" sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1.5, bgcolor: 'background.paper', p: { xs: 1.75, sm: 2.5 } }}>
        <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>{t.receptor}</Typography>
        <Typography sx={{ fontWeight: 700, fontSize: 16, mb: 1 }}>Cargo de recepción — Mesa de partes virtual</Typography>
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 2, mb: 1 }}>
          <Box>
            <Typography variant="caption" color="text.secondary">Expediente</Typography>
            <Typography sx={{ fontWeight: 700, fontSize: 20, letterSpacing: '0.02em' }}>{t.expediente}</Typography>
          </Box>
          <Box>
            <Typography variant="caption" color="text.secondary">Código de seguimiento</Typography>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <Typography sx={{ fontWeight: 700, fontSize: 20, fontFamily: 'ui-monospace, Consolas, monospace', color: PALETA.guinda }}>{t.codigo}</Typography>
              <Button size="small" className="no-imprimir" onClick={() => void copiar()} startIcon={<ContentCopyIcon fontSize="small" />}>Copiar</Button>
            </Box>
          </Box>
        </Box>
        <Divider sx={{ my: 1 }} />
        <Fila rotulo="Recibido">{fechaHora(t.recibido_en)} (hora de Lima)</Fila>
        {/* Con la mesa de 24 horas lo presentado es lo recibido: la fila solo sale si difiere. */}
        {presentadoOtroDia(t) && (
          <Fila rotulo="Se tiene por presentado el">
            {fechaHora(t.presentado_el)}{t.fuera_de_horario ? ' · llegó fuera del horario de atención' : ''}
          </Fila>
        )}
        <Fila rotulo="Remitente">{t.remitente.nombre} · {t.remitente.doc_tipo} {t.remitente.doc}</Fila>
        {t.remitente.representante && <Fila rotulo="Representante">{t.remitente.representante}{t.remitente.cargo ? ` (${t.remitente.cargo})` : ''}</Fila>}
        <Fila rotulo="Documento">{[t.documento.tipo, t.documento.numero].filter(Boolean).join(' ')} · {t.documento.folios} folio(s)</Fila>
        <Fila rotulo="Asunto">{t.documento.asunto}</Fila>
        {t.documento.referencia && <Fila rotulo="Referencia">{t.documento.referencia}</Fila>}
        <Divider sx={{ my: 1 }} />
        <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>Archivos recibidos</Typography>
        {t.archivos.map((a, i) => (
          <Box key={a.id} sx={{ py: 0.6, borderBottom: i < t.archivos.length - 1 ? '1px dashed' : 'none', borderColor: 'divider' }}>
            <Typography variant="body2" sx={{ wordBreak: 'break-word' }}>
              {i + 1}. {CLASE_ARCHIVO[a.clase]}: {a.nombre} · {peso(a.bytes)}{a.tipo === 'pdf' && a.paginas ? ` · ${a.paginas} pág.` : ''}
            </Typography>
            <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'ui-monospace, Consolas, monospace', wordBreak: 'break-all', display: 'block' }}>
              SHA-256 {a.sha256}
            </Typography>
          </Box>
        ))}
      </Box>
      <Alert severity="info" variant="outlined" sx={{ mt: 1.5 }} className="no-imprimir">
        Guarde su código: con él y su número de documento sigue el trámite aquí mismo. No enviamos correos.
      </Alert>
      {aviso && <Alert severity={aviso.tipo} sx={{ mt: 1 }} onClose={() => setAviso(null)} className="no-imprimir">{aviso.texto}</Alert>}
      <Box className="no-imprimir" sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, mt: 1.5 }}>
        <Button variant="contained" startIcon={<DownloadIcon />} onClick={() => void bajar()} sx={{ flex: { xs: '1 1 100%', sm: '0 0 auto' } }}>
          Descargar cargo (PDF)
        </Button>
        <Button variant="outlined" startIcon={<PrintOutlinedIcon />} onClick={() => window.print()} sx={{ flex: { xs: '1 1 45%', sm: '0 0 auto' } }}>
          Imprimir
        </Button>
        <Button variant="outlined" startIcon={<SearchIcon />} onClick={alSeguir} sx={{ flex: { xs: '1 1 45%', sm: '0 0 auto' } }}>
          Ver mi trámite
        </Button>
      </Box>
    </Box>
  )
}
