# DECISIONS

Respuestas a las tres preguntas del ENUNCIADO y registro de decisiones del Reto 1
("Vende los datos sin vender a la gente"). Todos los ejemplos son inventados: este archivo
no lleva datos reales del corpus. Diseño completo: `docs/diseno.html` (PDF: `docs/diseno.pdf`).

---

## 1. ¿Qué consideramos PII?

Principio: una persona se identifica por **llaves**, no por su nombre. Por eso se trata como PII
todo lo que nombra, contacta, ubica o permite enlazar a una persona natural, en cualquier rincón
de cualquier fuente (texto, claves, metadatos, nombres de archivo).

| Tipo | Ejemplos genéricos | Qué hacemos |
|---|---|---|
| Nombre completo y variantes | `Marta Rojas Pérez`, `Marta Rojas`, `Marta`, `MARTA ROJAS PEREZ` (mayúsculas y sin tildes, como en extractos) | Seudónimo del mismo género y región; cada forma corta se mapea a la parte equivalente del seudónimo |
| Apodos | `Marty` (de `display_name` en `users.json`) | Va al nombre de pila del seudónimo |
| Handles | `@mrojas`, `@marta.rojas` (front matter, texto) | Mismo patrón con el seudónimo |
| Slugs y parámetros en URL | `…/comercios/marta-rojas/pagos`, `…?u=mrojas`, `…?ref=mrojas`, `…/share/demo-marta-rojas` | Se reemplaza solo el slug o el valor; la URL queda válida |
| Correos | `mrojas@ejemplo.com`, `marta.rojas@empresa.co` | Correo con el mismo patrón (`inicial+apellido`, `nombre.apellido`) y dominio de la misma categoría |
| Correos deletreados | `mrojas arroba ejemplo punto com`, `marta punto rojas arroba ejemplo punto com` | Se reemplaza conservando la forma deletreada |
| Cédulas y documentos | `1.234.567.890`, `1234567890`, `CC 12 345 678`, con separadores raros | Número con formato válido y lejos del original; mismas variantes de escritura |
| Celulares | `300 123 4567`, `+57 300 123 4567`, `573001234567` | Celular válido (empieza con 3, 10 dígitos), con el mismo formato |
| Placas | `ABC123`, `ABC-123`, `abc 123` | Placa con el mismo patrón |
| Pasaportes | `XX123456` | Mismo patrón |
| Números de crédito y de cuenta | `4471-0000` (prefijo de producto + consecutivo) | Mismo formato, consistente entre carta, acta, transacción y metadatos |
| Direcciones | `Cra 12 # 34-56 apto 702`, `Calle 9 Bis # 8-10`, `Diagonal 3A # 4-5 of 201` | Dirección sintética con el mismo estilo |
| Fechas de nacimiento | `1990-05-17`, `17/05/1990` | Fecha cercana en rango, pero distinta |
| Metadatos de PDF | `Author`, `Subject`, `Keywords` con nombres o correos, incluso en UTF-16 | Se reemplazan en el valor; las claves se conservan |
| Metadatos HTML/Markdown | `<meta name="author">`, front matter `author:`, `reportado_por:`, `asistentes:` | Ídem |
| Comentarios | `<!-- revisado por … correo … -->` en HTML; comentarios XML con correo del exportador | Se reemplaza dentro del comentario |
| Nombres en archivos y adjuntos | `extracto_marta_rojas_sep.pdf`, `certificado_marta_rojas.pdf`, `CC1234567890_ingresos.pdf` | El nombre de archivo es campo y también texto: se anonimiza conservando la extensión |
| Terceros fuera de las tablas | "mi hermano Pedro", "mi mamá, Rosa", "mi jefe Andrés Mora", "cc del titular 1.234.567.890" | Reciben una llave estable `relación:persona ancla:nombre` y su propio seudónimo |
| Llaves entre personas | "mi novia Ana Pérez… es clienta" | Si el contexto lo confirma se une a la persona del maestro |
| Cuasi-identificadores | Oficio + barrio + año de vinculación ("arquitecta, vive en un barrio concreto, cliente desde 2021") | Se generalizan, no se borran: oficio → sector, barrio → otro de la misma ciudad o la ciudad, año → "hace unos años". Se evalúa sobre la unión chat + fila del maestro, y también tuplas sin nombre |

Lo que **no** es PII por sí solo: la ciudad, un barrio, un oficio o un año por separado. Lo es la
combinación que apunta a pocas personas; ahí se generaliza (k mínimo contra el maestro).

Qué NO hacemos: hashear (reversible por fuerza bruta en cédulas), dejar `[REDACTED]` (destruye
relaciones) ni reescribir con un modelo (el texto se **reemplaza**, nunca se redacta de nuevo).

## 2. ¿Qué conservamos a propósito y por qué?

| Se conserva | Ejemplos | Por qué |
|---|---|---|
| Organizaciones y marcas | bancos, billeteras, aerolíneas, supermercados, el regulador financiero, Kipu Pay con su NIT y su oficina | No son personas naturales; el comprador necesita ver con qué entidades habla el cliente. Se declaran en `entities.json` con `kept: true` y `reason` |
| Lugares | ciudades, barrios genéricos, parques, plazas, comercios de una zona | El texto sigue siendo reconocible para entrenar atención al cliente; el barrio solo se generaliza si, junto con oficio y año, identifica a alguien |
| Figuras públicas y marcas con nombre de persona | escritores, deportistas, una cadena de café con nombre propio | No son clientes ni empleados; borrarlas pierde utilidad (y el juez cuenta falsos positivos). Solo se conservan si están en la lista curada y no están en el grafo |
| Ciudad y fecha de vinculación | `Medellín`, `2022-02-22` | Por sí solas no identifican y son la señal de negocio más útil; solo se tocan si forman parte de una tupla que apunta a pocas personas |
| IDs de negocio | `cliente_id`, `tx_id`, `radicado`, `id` de empleado | Son las **llaves entre tablas**: el comprador debe poder unir las mismas filas. Son identificadores internos, no contacto ni documento |
| Montos y fechas de transacciones | `356.000`, `2026-09-19` | Es el contenido de negocio (y la forma de cruzar chat con transacciones); sin ellos no hay dataset |
| Texto no personal | políticas, tasas, plazos, nombres de producto | Es el 10 % de utilidad "parecido con la salida ideal" |

**Regla del apellido que también es lugar.** Un token como `Castilla`, `Santander`, `Bolívar` o
`Restrepo` sigue siendo **apellido** cuando nombra a una persona y **lugar u organización** cuando
nombra un lugar o un banco. Operativamente: solo se reemplaza dentro de un nombre completo, junto a
un honorífico ("señor Bolívar") o cuando el grafo lo liga a una persona; en una descripción de
transacción ("Compra … Castilla", "Parque … Bolívar", "Transferencia a Santander") se conserva. El
LLM de recall confirma en contexto, pero la decisión de conservar es determinística.

**Honestidad del diccionario.** `entities.json` declara todas las formas reales encontradas (no
menos), los registros donde aparecen y, para lo conservado, `kept` y `reason`.

## 3. ¿Cuánto cuesta correr el pipeline?

El pipeline determinista no usa tokens. Solo el LLM de recall (modelo barato vía OpenRouter, con
`temperature` 0, `max_tokens` acotado, 8 hilos, caché por hash del modelo + versión del prompt + unidad).
Una unidad es un hilo de chat completo, un documento, o un lote de filas de texto libre de tablas.

### Medido al precalentar la caché del LLM (corpus completo, sin conocidas)

Modelo `anthropic/claude-haiku-5.5`, sobre 352 unidades (320 hilos, 26 documentos, 6 lotes de tablas;
2.427 registros, ~222 mil caracteres de texto).

| Medición | Tokens in | Tokens out | USD | Segundos | Llamadas | Fallos |
|---|---:|---:|---:|---:|---:|---:|
| Prompt v1 (primer intento) | 664.725 | 270.367 | 0,202 | 186 | 352 | 2 (salida cortada por `max_tokens`) |
| **Prompt v2 (vigente)** | **705.557** | **237.856** | **0,189** | **184** | **352** | **0** |
| Segunda corrida con caché | 0 | 0 | 0,000 | < 1 | 0 (352 aciertos) | 0 |

La v2 le pide no listar ciudades ni comercios comunes y rescata respuestas cortadas; devolvió 909
menciones (889 persona, 20 tercero) y 30 sugerencias aparte (lugar, organización, figura pública).
Los tokens de entrada incluyen el system prompt repetido en cada llamada. Una corrida limpia vale
unos US$0,2 y ~3 minutos; con caché, casi cero.

### Corridas oficiales (llenar con las reales, `GET /run/{job_id}` → `cost`)

| Corrida | Fuentes servidas | Tokens in | Tokens out | USD | Segundos | Puntaje |
|---|---|---:|---:|---:|---:|---:|
| 1 (60 % de tests ocultos) | `{{FUENTES_1}}` | `{{TIN_1}}` | `{{TOUT_1}}` | `{{USD_1}}` | `{{SEG_1}}` | `{{PUNTAJE_1}}` |
| 2 (75 %) | `{{FUENTES_2}}` | `{{TIN_2}}` | `{{TOUT_2}}` | `{{USD_2}}` | `{{SEG_2}}` | `{{PUNTAJE_2}}` |
| 3 (100 %) | `{{FUENTES_3}}` | `{{TIN_3}}` | `{{TOUT_3}}` | `{{USD_3}}` | `{{SEG_3}}` | `{{PUNTAJE_3}}` |
| `/anonymize` (lote de hasta 50 registros) | — | `{{TIN_AN}}` | `{{TOUT_AN}}` | `{{USD_AN}}` | `{{SEG_AN}}` | — |

Presupuesto: US$45 en total para el día, de los cuales US$5 están reservados para el set oculto.
Las corridas oficiales gastan de esa reserva; por eso el modelo es barato y la caché evita repetir
unidades. Si el LLM no responde, el pipeline sigue con reglas (no se cae ni cambia de seudónimos).

---

## Decisiones

Horas de la jornada; las marcadas `{{HH:MM}}` se llenan con la hora real del commit
(`git log --format='%h %ad %s' --date=format:%H:%M`).

| Hora | Decisión | Alternativa descartada y por qué |
|---|---|---|
| 10:12 | **Elección del reto 1** (anonimizar el corpus de Kipu Pay). Contrato claro (`/run`, `/anonymize`, `entities.json`), se mide en local con `validar.mjs` y la muestra antes de gastar una de las 3 corridas, se defiende en 10 minutos y es Python con librería estándar | Reto 2 (agente sobre escritorio remoto): no se puede medir el puntaje antes de gastar corridas y exige un cliente RFB propio |
| 10:30–12:00 | **Diseño** (`docs/diseno.html`, versión simple primero, luego v2–v6 con hallazgos medidos sobre el corpus) | Empezar a codificar sin medir el corpus |
| 10:30–12:00 | **Grafo de identificadores en lugar de agrupar por nombre**: los nodos son llaves fuertes (cliente, empleado, uid, radicado, cédula, correo, celular, placa, pasaporte, crédito); el nombre es etiqueta | Agrupar por nombre: fusiona a los homónimos y a la agente con la clienta que se llama igual (consistencia y homónimos a cero) |
| 10:30–12:00 | **Reglas + LLM de recall cacheado.** Las reglas hacen lo seguro y reproducible; el LLM solo agrega terceros y desempata persona vs. lugar | Solo reglas: ~88. LLM de punta a punta: no determinista y reescribe (pierde parecido, puede inventar o borrar datos de negocio) |
| 10:30–12:00 | **Gazetteer sacado del propio corpus** (ciudades, barrios del maestro, comercios y lugares de transacciones) más listas curadas de organizaciones y figuras públicas | Lista genérica: no conoce los barrios ni los comercios de Kipu |
| 10:30–12:00 | **HMAC + mapa persistido** para los seudónimos: determinista, mismo género, mismo patrón, nunca igual a una persona real; el mapa vive en el volumen | Seudónimos al azar: rompen la consistencia entre corridas, y el 70 % del puntaje es la corrida posterior al crecimiento de las fuentes |
| 10:30–12:00 | **Generalizar siempre, ligado a la persona** (maestro: oficio, barrio, dirección, nacimiento; texto: los cuasi-identificadores de esa persona), más tuplas sin nombre | k-anonimato condicional: se cruza entre fuentes y se aleja de la salida ideal |
| 10:30–12:00 | **Juez local + ataque de enlace**: `evals/` replica `validar.mjs`, mide con la muestra, los tests públicos y una batería de trampas sacada del corpus | Iterar a ciegas con 3 corridas |
| `{{HH:MM}}` | **Defensas contra prompt injection** (diseño, sección 5): el LLM no tiene tools ni red; solo puede *agregar* detecciones; cada span se valida en código (existe literal en ese registro y campo, tipo en el enum, ≤ 80 caracteres); el texto viaja como JSON en el mensaje de usuario y la política en el system; NFKC e invisibles/confusables fuera antes de enviar; `conservado` exige gazetteer o lista curada y no estar en el grafo; canarios de inyección en `evals/` | Confiar en que el prompt "resista": las defensas probabilísticas se rompen con atacantes adaptativos |
| `{{HH:MM}}` | **Token del equipo obligatorio en todas las rutas excepto `GET /health`** (comparación en tiempo constante) | Rutas abiertas: `/entities` contiene las formas originales, así que jamás puede ser público |
| `{{HH:MM}}` | **SSRF cerrado en `/run`**: solo `https`, IP pública, sin redirecciones, conexión fijada a la IP validada | Aceptar cualquier `sources_url` |
| `{{HH:MM}}` | **Despliegue en Railway**: 1 réplica, sin reposo, volumen en `DATA_DIR`, healthcheck en `/v1/health` | Vercel serverless: no sirve para tareas de minutos con estado |
| `{{HH:MM}}` | **Dependencias**: ninguna. Python 3.12 con `http.server`, `urllib`, `zlib`, `hashlib`, `hmac`, `difflib`, `unittest`; Node solo para correr `validar.mjs` en local | Presidio, spaCy y similares: prohibidos por el reto y contra la regla del evento de usar la menor cantidad de librerías |

### Trade-offs del doc de diseño

- **Separar antes que fusionar.** Un nombre de pila sin evidencia queda como persona aparte: pierde
  un poco de consistencia, pero no mezcla a dos personas (que sería fuga y homónimos a la vez).
- **Evidencia, no nombre.** Resolución por llave en el registro > identificador fuerte en el hilo >
  fecha + monto que cruza con transacciones > adjunto > participantes del hilo.
- **Reemplazar, no reescribir.** Cuesta menos, no inventa datos y se parece a la salida ideal; a
  cambio, el pipeline necesita detectar todas las formas (de ahí el recall del LLM y el barrido final).
- **Verificar antes de publicar.** Barrido global de formas con la normalización del juez, ataque
  de enlace contra el maestro original y `validar.mjs`; si algo falla se corrige y se repite.
- **LLM caído → reglas.** Coste: algún tercero sin detectar. Beneficio: el servicio nunca se cae ni
  cambia seudónimos (el mapa es determinista y persistido).
- **Costo acotado.** `max_tokens` y modelo barato por defecto; caché por hash; el LLM ve solo texto
  libre, no las columnas estructuradas.
- **Fuentes que crecen.** El grafo se extiende sin renumerar; una persona vieja con un identificador
  nuevo se une a su componente; las nuevas reciben seudónimos nuevos y únicos.

### Límites conocidos

- Un tercero que solo aparece con nombre de pila y sin ninguna evidencia queda como persona aparte.
- Los tests ocultos usan mecanismos distintos de los públicos; el juez local es una estimación
  (aproximada), no una garantía del puntaje.
- La heurística de género de nombres nuevos y la lista curada de figuras públicas son finitas.
