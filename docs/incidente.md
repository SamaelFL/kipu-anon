# Incidente INC-PII-01: Kipu Pay compró Págalo

Las fuentes crecieron a media jornada, como anunciaba el enunciado. Este documento resume qué cambió,
cómo se detectó, cómo se adaptó el servicio y con qué evidencia. Sin datos reales del corpus.

## Qué cambió

| | Antes | Después |
|---|---:|---:|
| Mensajes de chat | 2.028 | 2.999 |
| Documentos | 26 | 34 |
| Filas de tablas | 6.243 | 7.823 |
| Usuarios de Slack | 187 | 235 |
| Clientes en el maestro | 149 | 203 (54 con id `PG-`) |

- Dos canales nuevos (soporte y migración de Págalo) y fechas nuevas en canales viejos.
- Ocho documentos nuevos, dos en inglés (contrato de compra de cartera y aviso de cesión).
- **Trampas encontradas al medir:**
  - 12 clientes migrados traen un `cliente_id` nuevo (`PG-`) con la misma cédula, correo y celular que su fila `CL-` (misma persona, identificador nuevo).
  - 3 usuarios viejos de Slack aparecen con el nombre recortado y sin correo, justo cuando llegan usuarios nuevos que se llaman igual (persona nueva con nombre de persona vieja).
  - "Nada de lo anterior cambia" no se cumplía para `users.json`.

## Detección

- Canario sobre `GET /record_index` cada 5 minutos con `If-None-Match`; línea base 12:11.
- El ticket se abrió a las 15:00, pero el API siguió respondiendo 304 con el mismo ETag. Se verificó por fuera del canario (pedido completo sin caché a `record_index`, `/docs`, `/tables`, `/chats/channels`, `/chats/users`) y el staff confirmó un error de su lado.
- Al servirse los datos nuevos, `evals/bajar_fuentes.py` espejó el API y resumió el cambio (conteos, canales, fechas, usuarios, documentos y filas nuevas).

## Adaptación

1. **Nada se corre en Railway sin probar en local.** El código viejo sobre datos nuevos habría sobrescrito el grafo y el `entities.json` del volumen, que son la referencia de estabilidad.
2. **Enlaces anclados.** Cada usuario de Slack conserva la persona que tenía en la corrida anterior (`grafo.json` del volumen), aunque su perfil cambie o llegue un homónimo.
3. **Mismo cliente, otro id.** Una fila nueva cuya cédula, correo o celular ya son de un solo cliente es ese cliente. `PG-xxxx` apunta a la misma entidad y hereda su seudónimo.
4. **Seudónimos ya entregados se conservan.** Si los datos nuevos solo traen números parecidos, el valor declarado antes se mantiene. Solo cambia si ahora sería un dato real de otra persona: ocurrió con una fecha de nacimiento, y ahí manda la privacidad.
5. **Revisión manual de homónimos y consistencia** (16:50–17:39), cada regla con su caso:
   - radicado en la misma línea de las tablas de PQR
   - solo el nombre más cercano al radicado
   - últimos dígitos de la cédula
   - cargo o ciudad en aposición ("agente de Cali")
   - oficio descrito en la frase
   - empleado único por nombre de pila en canales internos
   - obra literaria intacta
   - cédula tras "ID No." en contratos en inglés
   - nombre partido por salto de línea en PDF
   - números por letras
   - direcciones con "número" o sin guion

## Evidencia

- `evals/diff_entities.py` contra el `entities.json` de la corrida 1: 192 personas viejas, 0 desaparecidas, 191 con los mismos seudónimos (la otra, solo la fecha mencionada), 0 choques con seudónimos nuevos.
- Cada despliegue se comparó registro por registro contra el anterior: solo cambiaban los registros que el arreglo debía cambiar. La salida de Railway es idéntica a la local.
- `validar.mjs` en verde en todas las corridas; 110 pruebas unitarias; 25 regresiones sobre las trampas; 42 variantes de ofuscación en vivo contra `/anonymize`.
- Set oculto: 78/95 → 130/156 → **181/205**, con 0 fallas de fuga directa en la corrida final.

## Pendiente

- Enmascarar terminaciones parciales ("cédula terminada en 1234") con las del seudónimo.
- Desempate semántico de homónimos con evidencia verificable cuando el texto no trae llaves.
- Quedan 16 fallas de consistencia, 5 de indirecta y 3 de homónimos sin causa identificada (la plataforma no muestra los casos).
