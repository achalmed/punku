/**
 * La Mesa de Partes SOLA en el navegador (Punku): la cáscara mínima de Tiqsi con el módulo web de la Mesa de Partes, contra el
 * anfitrión mínimo del backend (punku/sola.py). No importa nada de Qillqa. Se construye desde la raíz con
 * `npm run web:construir`.
 */
import { createRoot } from 'react-dom/client'
import { CascaronMinimo } from '@qillqa/tiqsi/minimo'
import { PUNKU } from './componentes/entradas/modulo'

createRoot(document.getElementById('root')!).render(<CascaronMinimo modulo={PUNKU} />)
