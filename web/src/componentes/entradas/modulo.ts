/**
 * El módulo web de la Mesa de Partes (proyecto Punku; fase 10.2b P4 del contrato de Tiqsi, 2026-10-20): su pantalla, su
 * ruta, su página pública y cómo entra al menú del anfitrión. Qillqa arma con esto su entrada en el menú (navegacion.ts)
 * y sus rutas (App.tsx); la página de la Mesa de Partes SOLA (src/punku_sola.tsx), su cáscara mínima.
 *
 * Lo que llega al despacho —cartas, oficios, invitaciones, citaciones, y lo que entra por la mesa de partes virtual—
 * con su ficha, responsable, plazo y respuesta (antes «Recibidos»; módulo propio desde el 2026-10-12). El id, la ruta
 * (`/recibidos`) y la API (`entradas`) no cambian: solo lo visible. La mesa de partes virtual es PÚBLICA, sin sesión:
 * quien envía documentos al despacho no tiene cuenta (backend/app/api/mesa_publica.py).
 */
import MoveToInboxOutlinedIcon from '@mui/icons-material/MoveToInboxOutlined'
import PendingActionsOutlinedIcon from '@mui/icons-material/PendingActionsOutlined'
import EventBusyOutlinedIcon from '@mui/icons-material/EventBusyOutlined'
import FormatListBulletedIcon from '@mui/icons-material/FormatListBulleted'
import UploadFileOutlinedIcon from '@mui/icons-material/UploadFileOutlined'
import { definirModuloWeb } from '@qillqa/tiqsi'

export const PUNKU = definirModuloWeb({
  id: 'recibidos',
  nombre: 'Mesa de Partes',
  corto: 'Mesa de Partes',
  ruta: '/recibidos',
  icono: MoveToInboxOutlinedIcon,
  descripcion: 'Lo que llega al despacho, también por la mesa de partes virtual: ficha, responsable, plazo y respuesta.',
  opciones: [
    { etiqueta: 'Pendientes', ruta: '/recibidos?estado=nueva', icono: MoveToInboxOutlinedIcon, ayuda: 'Documentos sin atender todavía' },
    { etiqueta: 'En atención', ruta: '/recibidos?estado=en_atencion', icono: PendingActionsOutlinedIcon, ayuda: 'Con responsable y en trámite' },
    { etiqueta: 'Vencidos', ruta: '/recibidos?vencidas=1', icono: EventBusyOutlinedIcon, ayuda: 'Con el plazo de atención pasado' },
    { etiqueta: 'Todos', ruta: '/recibidos?estado=todas', icono: FormatListBulletedIcon, ayuda: 'También los atendidos y archivados' },
    { etiqueta: 'Registrar documentos', ruta: '/recibidos?subir=1', icono: UploadFileOutlinedIcon, accion: true, ayuda: 'Subir los PDF que llegaron; el sistema lee su ficha' },
  ],
  cargar: () => import('../../paginas/Entradas'),
  publicas: [{ ruta: '/mesa-de-partes/*', cargar: () => import('../../paginas/MesaVirtual') }],
})
