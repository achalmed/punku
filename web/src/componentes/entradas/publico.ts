/**
 * Lo que la web de la Mesa de Partes ofrece a otros (proyecto Punku; fase 10.2b P4, 2026-10-20): el equivalente web de
 * «recibidos.v1». Nadie fuera de la Mesa de Partes importa sus archivos internos; solo esto y su `modulo.ts` (lo
 * comprueba backend/tests/test_fronteras.py). Lo usan el Inicio de Qillqa (la tarjeta de lo recibido) y Administración
 * (la configuración de la mesa virtual, debajo de su interruptor). Al extraer Punku, es lo que exporta su paquete web.
 */
export { default as ResumenRecibidos } from './ResumenRecibidos'
export type { ResumenEntradas } from './modelo'
export { default as AdminMesaVirtual } from '../AdminMesaVirtual'
