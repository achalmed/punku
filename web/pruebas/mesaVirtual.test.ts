// Pruebas de la lógica pura de la mesa de partes virtual (2026-10-12). Correr desde frontend/:
//   node --test pruebas/*.test.ts
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { errorDoc, fechaHora, peso, rucValido, soloDoc, textoHorario } from '../src/componentes/mesa/modelo.ts'

const conVerificador = (base: string) => {
  const pesos = [5, 4, 3, 2, 7, 6, 5, 4, 3, 2]
  const resto = 11 - (pesos.reduce((s, p, i) => s + p * Number(base[i]), 0) % 11)
  return base + String(resto >= 10 ? resto - 10 : resto)
}

test('RUC: dígito verificador y prefijos, como el servidor', () => {
  const ruc = conVerificador('2013131295')
  assert.ok(rucValido(ruc))
  assert.ok(!rucValido(ruc.slice(0, 10) + String((Number(ruc[10]) + 1) % 10)))
  assert.ok(!rucValido('3013131295' + '5'))
  assert.equal(errorDoc('RUC', ruc), '')
})

test('documentos de persona y limpieza', () => {
  assert.equal(soloDoc(' 12.345.678 '), '12345678')
  assert.equal(errorDoc('DNI', '12345678'), '')
  assert.notEqual(errorDoc('DNI', '1234567'), '')
  assert.equal(errorDoc('CE', soloDoc('00-1234567')), '')
})

test('horario, fechas y pesos legibles', () => {
  assert.equal(textoHorario({ inicio: '08:30', fin: '17:30', dias: [0, 1, 2, 3, 4] }), 'lunes a viernes, de 08:30 a 17:30')
  assert.equal(textoHorario({ inicio: '09:00', fin: '13:00', dias: [0, 2, 4] }), 'lunes, miércoles, viernes, de 09:00 a 13:00')
  assert.equal(fechaHora('2026-10-13'), '13/10/2026')
  assert.equal(fechaHora('2026-10-12T22:14'), '12/10/2026 22:14')
  assert.equal(peso(1536), '2 KB')
  assert.equal(peso(3 * 1024 * 1024), '3.0 MB')
})
