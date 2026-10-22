/**
 * Elegir archivos para la mesa de partes virtual (2026-10-12): un botón grande (en el celular abre
 * la galería, la cámara o los archivos), la lista con el peso de cada uno y el total, y quitar.
 * La comprobación de verdad la hace el servidor por la firma de bytes; aquí solo se avisa antes de
 * enviar lo que de seguro no pasará (tipo por la extensión, tamaño).
 */
import { useRef } from 'react'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import Typography from '@mui/material/Typography'
import AttachFileIcon from '@mui/icons-material/AttachFile'
import CloseIcon from '@mui/icons-material/Close'
import PictureAsPdfOutlinedIcon from '@mui/icons-material/PictureAsPdfOutlined'
import ImageOutlinedIcon from '@mui/icons-material/ImageOutlined'
import { PALETA } from '@qillqa/tiqsi'
import { peso } from './modelo'

export const SOLO_PDF = /\.pdf$/i
export const PDF_O_IMAGEN = /\.(pdf|jpe?g|png)$/i

/** Motivo por el que un archivo no se acepta (vacío si se acepta). */
export function motivoArchivo(f: File, admitidos: RegExp, maxMb: number): string {
  if (!admitidos.test(f.name)) return admitidos === SOLO_PDF ? 'debe ser un PDF' : 'solo PDF, JPG o PNG'
  if (f.size === 0) return 'está vacío'
  if (f.size > maxMb * 1024 * 1024) return `pesa más de ${maxMb} MB`
  return ''
}

export default function ElegirArchivos({
  etiqueta,
  archivos,
  alCambiar,
  multiple = false,
  maximo = 1,
  admitidos = SOLO_PDF,
  maxMb,
  error = '',
  id,
}: {
  etiqueta: string
  archivos: File[]
  alCambiar: (a: File[]) => void
  multiple?: boolean
  maximo?: number
  admitidos?: RegExp
  maxMb: number
  error?: string
  id: string
}) {
  const entrada = useRef<HTMLInputElement | null>(null)
  const lleno = archivos.length >= maximo
  return (
    <Box>
      <input
        ref={entrada}
        id={id}
        type="file"
        hidden
        multiple={multiple}
        accept={admitidos === SOLO_PDF ? 'application/pdf,.pdf' : 'application/pdf,.pdf,image/jpeg,.jpg,.jpeg,image/png,.png'}
        onChange={(e) => {
          const nuevos = Array.from(e.target.files ?? [])
          e.target.value = ''
          alCambiar(multiple ? [...archivos, ...nuevos].slice(0, maximo) : nuevos.slice(0, 1))
        }}
      />
      <Button
        variant="outlined"
        startIcon={<AttachFileIcon />}
        onClick={() => entrada.current?.click()}
        disabled={lleno && multiple}
        fullWidth
        sx={{ py: 1.25, justifyContent: 'flex-start', borderStyle: 'dashed', borderColor: error ? 'error.main' : undefined }}
        aria-describedby={`${id}-ayuda`}
      >
        {archivos.length && !multiple ? 'Cambiar el archivo' : etiqueta}
      </Button>
      {archivos.length > 0 && (
        <Box component="ul" sx={{ listStyle: 'none', p: 0, m: 0, mt: 1, display: 'flex', flexDirection: 'column', gap: 0.75 }}>
          {archivos.map((f, i) => {
            const motivo = motivoArchivo(f, admitidos, maxMb)
            return (
              <Box component="li" key={`${f.name}-${i}`} sx={{ display: 'flex', alignItems: 'center', gap: 1, p: 1, border: '1px solid', borderColor: motivo ? 'error.main' : 'divider', borderRadius: 1, bgcolor: 'background.paper' }}>
                {SOLO_PDF.test(f.name) ? <PictureAsPdfOutlinedIcon sx={{ color: PALETA.guinda }} /> : <ImageOutlinedIcon sx={{ color: PALETA.textoTenue }} />}
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Typography variant="body2" noWrap title={f.name}>{f.name}</Typography>
                  <Typography variant="caption" color={motivo ? 'error' : 'text.secondary'}>
                    {peso(f.size)}{motivo ? ` · ${motivo}` : ''}
                  </Typography>
                </Box>
                <IconButton size="small" aria-label={`Quitar ${f.name}`} onClick={() => alCambiar(archivos.filter((_, j) => j !== i))}>
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Box>
            )
          })}
        </Box>
      )}
      {error && <Typography variant="caption" color="error" role="alert" sx={{ display: 'block', mt: 0.5 }}>{error}</Typography>}
    </Box>
  )
}
