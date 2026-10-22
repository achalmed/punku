/**
 * La FICHA de un documento recibido, editable (2026-10-06): la misma en la vista
 * previa de la subida (antes de registrar) y en el panel de detalle. Lo que la
 * ficha automática no supo leer se completa aquí; el remitente se elige del
 * directorio (o queda como texto libre).
 */
import Box from '@mui/material/Box'
import TextField from '@mui/material/TextField'
import MenuItem from '@mui/material/MenuItem'
import Checkbox from '@mui/material/Checkbox'
import FormControlLabel from '@mui/material/FormControlLabel'
import Autocomplete from '@mui/material/Autocomplete'
import Typography from '@mui/material/Typography'
import type { MiembroEquipo } from './apoyo'
import { AutocompletadoDirectorio } from './piezas'
import { ATENCIONES, CATEGORIAS, CLASES, VIAS, type DatosFicha } from './modelo'

export default function FormularioFicha({
  valor,
  alCambiar,
  equipo,
  campanas,
  sinAsignacion = false,
  soloLectura = false,
}: {
  valor: DatosFicha
  alCambiar: (cambio: Partial<DatosFicha>) => void
  equipo: MiembroEquipo[]
  campanas: string[]
  /** En la subida la asignación es opcional: se muestra igual, más abajo. */
  sinAsignacion?: boolean
  soloLectura?: boolean
}) {
  const fila = { display: 'grid', gap: 1.25, gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' } }
  const campo = (clave: keyof DatosFicha, etiqueta: string, extra: object = {}) => (
    <TextField
      size="small"
      label={etiqueta}
      value={(valor[clave] as string | null) ?? ''}
      onChange={(e) => alCambiar({ [clave]: e.target.value } as Partial<DatosFicha>)}
      InputProps={{ readOnly: soloLectura }}
      fullWidth
      {...extra}
    />
  )
  const fecha = (clave: 'fecha_documento' | 'fecha_recepcion' | 'plazo', etiqueta: string) =>
    campo(clave, etiqueta, { type: 'date', InputLabelProps: { shrink: true } })

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25 }}>
      <Box sx={fila}>
        {campo('documento', 'Documento (tipo y número)', { placeholder: 'Oficio N° 0456-2026-…' })}
        {campo('std_numero', 'N.° de registro STD', { inputProps: { inputMode: 'numeric' } })}
      </Box>
      {soloLectura ? (
        campo('remitente', 'Remitente')
      ) : (
        <AutocompletadoDirectorio
          etiqueta="Remitente (persona o institución del directorio, o texto libre)"
          valor={valor.remitente}
          alEscribir={(v) => alCambiar({ remitente: v, remitente_persona_id: null, remitente_institucion_id: null })}
          alElegir={(e) =>
            e.ref.tipo === 'persona'
              ? alCambiar({
                  remitente: e.nombre,
                  remitente_cargo: e.cargo || valor.remitente_cargo,
                  remitente_persona_id: e.ref.datos.id,
                  remitente_institucion_id: e.ref.datos.institucion_id,
                })
              : alCambiar({ remitente: e.ref.datos.nombre, remitente_persona_id: null, remitente_institucion_id: e.ref.datos.id })
          }
        />
      )}
      <Box sx={fila}>
        {campo('remitente_cargo', 'Cargo del remitente')}
        {campo('via', 'Vía de llegada', {
          select: true,
          children: VIAS.map((v) => <MenuItem key={v.v} value={v.v}>{v.t}</MenuItem>),
        })}
      </Box>
      {campo('asunto', 'Asunto', { multiline: true, minRows: 2 })}
      {campo('referencia', 'Referencia (lo que cita el documento)')}
      <Box sx={fila}>
        {campo('clase', 'Clase', {
          select: true,
          children: CLASES.map((c) => <MenuItem key={c.v} value={c.v}>{c.t}</MenuItem>),
        })}
        {fecha('fecha_documento', 'Fecha del documento')}
      </Box>
      {/* Categoría (2026-10-18): qué es para el despacho; «Por revisar» si la IA dudó o nadie la confirmó. */}
      <Box sx={fila}>
        {campo('categoria', 'Categoría', {
          select: true,
          children: [<MenuItem key="" value=""><em>Sin clasificar</em></MenuItem>, ...CATEGORIAS.map((c) => (
            <MenuItem key={c.v} value={c.v}>
              <Box>
                <Typography variant="body2">{c.t}</Typography>
                <Typography variant="caption" color="text.secondary">{c.ayuda}</Typography>
              </Box>
            </MenuItem>
          ))],
        })}
        <FormControlLabel
          sx={{ ml: 0, mr: 0, alignSelf: 'center', flex: '1 1 160px', minWidth: 0 }}
          control={<Checkbox size="small" checked={Boolean(valor.requiere_revision)} disabled={soloLectura} onChange={(e) => alCambiar({ requiere_revision: e.target.checked })} />}
          label={<Typography variant="body2">Por revisar</Typography>}
        />
      </Box>
      {campo('resumen', 'Resumen', { multiline: true, minRows: 2, maxRows: 8 })}

      <Typography variant="overline" sx={{ color: 'text.secondary', lineHeight: 1.6, mt: 0.5 }}>
        Atención
      </Typography>
      <Box sx={fila}>
        {campo('atencion', 'Tipo de atención', {
          select: true,
          children: ATENCIONES.map((a) => (
            <MenuItem key={a.v} value={a.v}>
              <Box>
                <Typography variant="body2">{a.t}</Typography>
                <Typography variant="caption" color="text.secondary">{a.ayuda}</Typography>
              </Box>
            </MenuItem>
          )),
          SelectProps: { renderValue: (v: unknown) => ATENCIONES.find((a) => a.v === v)?.t ?? String(v) },
        })}
        {fecha('plazo', 'Plazo de atención')}
      </Box>
      <Box sx={fila}>
        {!sinAsignacion || equipo.length ? (
          <TextField
            size="small"
            select
            label="Responsable"
            value={valor.responsable_id ?? ''}
            onChange={(e) => alCambiar({ responsable_id: e.target.value === '' ? null : Number(e.target.value) })}
            InputProps={{ readOnly: soloLectura }}
            fullWidth
          >
            <MenuItem value="">
              <em>Sin responsable</em>
            </MenuItem>
            {equipo.map((m) => (
              <MenuItem key={m.id} value={m.id}>
                {m.nombre_completo}
                {m.cargo ? <Typography component="span" variant="caption" color="text.secondary">&nbsp;· {m.cargo}</Typography> : null}
              </MenuItem>
            ))}
          </TextField>
        ) : (
          <span />
        )}
        {fecha('fecha_recepcion', 'Fecha de recepción')}
      </Box>
      <Autocomplete
        freeSolo
        options={campanas}
        value={valor.campana}
        inputValue={valor.campana}
        onInputChange={(_, v) => alCambiar({ campana: v })}
        readOnly={soloLectura}
        renderInput={(p) => (
          <TextField {...p} size="small" label="Campaña o grupo (opcional)" helperText="Agrupa cartas iguales de varios remitentes" />
        )}
      />
      {!sinAsignacion && campo('nota', 'Nota interna', { multiline: true, minRows: 1, maxRows: 6 })}
    </Box>
  )
}
