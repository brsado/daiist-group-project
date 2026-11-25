# Tareas del equipo

Este archivo reparte lo que falta del trabajo. Cada parte la hace **una persona, en su
ordenador, con su usuario de GitHub**, y esa persona tiene que poder explicarla en la
presentación (el profesor elige quién contesta cada pregunta).

Entrega: **lunes 30 de noviembre, 23:59**. Presentación: del 1 al 3 de diciembre.

| Parte | Qué es | Persona | Depende de |
|---|---|---|---|
| A | Casos de evaluación | _(nombre)_ | — (va primero) |
| B | Etiquetas humanas y juez | _(nombre)_ | A |
| C | Umbrales y decisión go / no-go | _(nombre)_ | A |
| D | Business case y análisis de fallos | _(nombre)_ | A, C |
| E | Operación online y presentación | _(nombre)_ | — |
| F | Bonus de aprendizaje por refuerzo (opcional) | _(nombre)_ | — |

Bruno ya ha hecho la base técnica (ver CONTRIBUTIONS.md).

---

## 1. Ponerlo en marcha (todos, 10 minutos)

1. Instala [uv](https://docs.astral.sh/uv/getting-started/installation/).
2. Clona el repo y entra en la carpeta:
   ```bash
   git clone https://github.com/brsado/daiist-group-project.git
   cd daiist-group-project
   uv sync
   ```
3. Crea tu clave gratuita de Gemini en <https://aistudio.google.com/apikey>.
4. `cp .env.example .env` y pega tu clave detrás de `GEMINI_API_KEY=` (sin espacios ni comillas).
   El `.env` no se sube nunca.
5. `uv run python app.py` y abre <http://127.0.0.1:7860>. Prueba un ejemplo.

## 2. Cómo funciona, en una página

La app es un **auditor de llamadas** para la persona que supervisa la atención telefónica de un
ayuntamiento inventado, Valdeolmo. Cada llamada (su transcripción) pasa por:

1. **Componente A, enrutador** (`router.py`, agente LLM con Gemini): usa dos herramientas
   (`info_categoria`, `buscar_tramite`) sobre `data/municipio.json` y decide la categoría (una de
   16), el departamento, la acción (guiar / transferir / persona / fuera de ámbito) y una respuesta.
2. **Componente B, auditor** (`auditor.py`, ML con scikit-learn): recibe la frase **y la decisión
   de A**, y calcula la probabilidad de que A haya acertado. Está entrenado con `data/phrases.csv`.
3. **Regla de revisión** (`pipeline.py`): si B no está de acuerdo, o la probabilidad baja del
   umbral, la llamada va a una persona.
4. **Registro** (`logbook.py`) y **Monitoring** (`monitor.py`): calidad, drift y alertas.

Comandos útiles:
```bash
uv run python main.py evaluate     # evaluación completa -> eval/summary.json, eval/results.csv
uv run python main.py drift-demo   # la alarma debe callar con normales y saltar con desplazadas
uv run python check.py             # lo que ejecuta el profesor
```
Las respuestas de Gemini se guardan en `cache/`, así que repetir no gasta cuota.

## 3. Reglas para trabajar

- **Commits con tu usuario**, pequeños y con un mensaje claro. Antes de empezar, `git pull`.
- **Añade tu línea en `CONTRIBUTIONS.md`** cada vez que acabes algo (fecha, nombre, qué).
- **Puedes usar Claude u otra IA para el código**, y hay que declararlo en el REPORT ("AI use").
  Pero según el enunciado, **las decisiones, los casos de prueba, las etiquetas y el análisis
  tienen que ser vuestros**. Los prompts de abajo están hechos para que la IA te explique y te
  prepare las cosas, **no para que decida por ti**.
- No escribas datos personales en ningún sitio: nombres, teléfonos, DNI, emails.

---

## Parte A · Casos de evaluación

**Objetivo:** que `eval/cases.csv` sea un buen examen del producto. Ahora tiene 36 casos de
borrador demasiado fáciles: el enrutador acierta el 100%, así que no sabemos si el auditor sirve.

**Archivos:** `eval/cases.csv` (formato en `eval/README.md`).

**Lo que decides tú:**
- Reescribir o validar los 36 casos y llegar a **40 o más**. Mínimos: 5 `hard`, 5 `review`,
  3 `out_of_scope` y suficientes `normal`.
- Unos **10 casos donde Gemini pueda equivocarse**: categorías vecinas (una terraza de bar: ¿negocio
  o vía pública?), frases vagas, dos motivos a la vez, canario muy cerrado, ironía.
- El `expected` de cada caso (`Categoría | acción`) y el `baseline` (qué pasaría hoy: todo al 301).
- Las frases tienen que ser **tuyas y realistas**, no generadas por la IA que estamos evaluando.

**Cómo comprobarlo:** `uv run python main.py evaluate` y mira `eval/results.csv` (columnas
`a_correct`, `review`, `correct`). `uv run python check.py` tiene que seguir pasando.

**Prompt para Claude:**
> Estoy en el repo daiist-group-project (lee TAREAS.md, parte A, y eval/README.md). Me encargo de
> los casos de evaluación en eval/cases.csv. No escribas los casos por mí: el enunciado exige
> que sean del equipo. Explícame el formato y las 16 categorías de data/municipio.json, revisa
> los casos que yo escriba (formato, que `expected` use una categoría y una acción válidas,
> mínimos por tipo) y dime cuáles son demasiado fáciles. Cuando termine, ejecuta
> `uv run python main.py evaluate` y explícame los resultados.

---

## Parte B · Etiquetas humanas y juez LLM

**Objetivo:** comprobar si el juez LLM (que puntúa las respuestas del enrutador) opina como
nosotros. El enunciado pide **20 o más etiquetas propias** y medir el acuerdo.

**Archivos:** `eval/to_label.csv` (lo genera la evaluación), `eval/human_labels.csv`, y el
`JUDGE_PROMPT` en `evaluate.py`.

**Lo que decides tú:**
- `pass` o `fail` y un comentario corto para 20 o más respuestas, con la misma rúbrica que el
  juez (la tienes en `JUDGE_PROMPT`). Cópialas en `eval/human_labels.csv` (`id,label,comment`).
- Si el acuerdo sale bajo: por qué, y si hay que cambiar la rúbrica.

**Depende de:** la parte A (etiqueta las respuestas de los casos definitivos).

**Cómo comprobarlo:** `uv run python main.py evaluate` → en `eval/summary.json`,
`judge.agreement_with_humans`.

**Prompt para Claude:**
> Estoy en el repo daiist-group-project (lee TAREAS.md, parte B). Me encargo de etiquetar a mano
> 20+ respuestas del enrutador en eval/human_labels.csv. No pongas tú las etiquetas: tienen que
> ser mías. Explícame la rúbrica del juez (JUDGE_PROMPT en evaluate.py), enséñame las respuestas
> de eval/to_label.csv de una en una para que yo decida pass/fail, y después calcula el acuerdo
> y ayúdame a entender los casos en que el juez y yo no coincidimos.

---

## Parte C · Umbrales y decisión

**Objetivo:** elegir con números cuándo una llamada va a revisión y cuándo saltan las alertas,
y decidir **go / no-go / go con condiciones**.

**Archivos:** `eval/threshold_sweep.csv` (lo genera la evaluación), `REVIEW_BELOW_P` en
`pipeline.py`, `AGREEMENT_ALERT`, `THUMBS_DOWN_ALERT` y `DRIFT_FEATURES` en `monitor.py`.

**Lo que decides tú:**
- El umbral de revisión: compara en `threshold_sweep.csv` cuántos errores del enrutador se cazan
  y cuántas falsas alarmas hay con cada umbral.
- Cuántas llamadas al día recibe un ayuntamiento pequeño (con fuente o supuesto razonado) y,
  por tanto, cuántas iría a revisar el supervisor al día.
- Los umbrales de las alertas, con su justificación.
- La decisión y sus condiciones, en la sección *Decision* del REPORT.

**Depende de:** la parte A.

**Cómo comprobarlo:** después de cambiar un umbral, `main.py evaluate`, `main.py drift-demo` y
`check.py`.

**Prompt para Claude:**
> Estoy en el repo daiist-group-project (lee TAREAS.md, parte C). Me encargo de los umbrales y de
> la decisión go / no-go. No elijas tú los umbrales ni la decisión. Explícame qué significa cada
> columna de eval/threshold_sweep.csv y de eval/summary.json, y qué hace cada umbral de
> pipeline.py y monitor.py. Ayúdame a calcular, con el volumen de llamadas que yo te diga,
> cuántas llamadas al día irían a revisión y cuánto costaría al mes. Revisa que mi justificación
> sea coherente con los números.

---

## Parte D · Business case y fallos

**Objetivo:** las secciones *Business case* y *Failures* del REPORT.

**Lo que decides tú:**
- Quién usa el producto, qué decisión apoya, cuál es el baseline (hoy: todo a Atención al
  Ciudadano, o un supervisor que escucha un 10% al azar), cómo medimos el éxito y **cuánto vale en
  euros**, con los supuestos (sueldo del supervisor, tiempo por llamada mal enrutada, volumen…).
- Los fallos de la evaluación agrupados por causa: enrutador, auditor o el paso de uno a otro;
  cuántos de cada tipo y qué arreglaríais primero.

**Depende de:** A (los fallos salen de los casos definitivos) y C (el volumen).

**Prompt para Claude:**
> Estoy en el repo daiist-group-project (lee TAREAS.md, parte D, y REPORT.md). Me encargo del
> business case y del análisis de fallos. El análisis tiene que ser mío. Ayúdame a ordenar los
> casos fallidos de eval/results.csv por causa (enrutador, auditor o el paso entre ambos), a
> hacer bien las cuentas del valor en euros con los supuestos que yo te dé, y revisa que lo que
> escribo sea claro y no pase de lo que permite el límite de palabras.

---

## Parte E · Operación online y presentación

**Objetivo:** la app online funcionando y una presentación de 6 minutos con la demo en directo.

**Lo que haces:**
- Comprobar la app online, `https://auditor-llamadas-valdeolmo.onrender.com` (Bruno la crea):
  `uv run python check.py --url https://auditor-llamadas-valdeolmo.onrender.com`.
- Sección *Operations* del REPORT: comprobar los números y añadir una captura o tabla de la demo
  de drift (`main.py drift-demo`).
- Guion de la presentación: un caso normal, uno que va a revisión y la pestaña Monitoring.
  Graba un vídeo de respaldo por si falla la red.
- Preparar con todo el equipo las preguntas más probables.

**Prompt para Claude:**
> Estoy en el repo daiist-group-project (lee TAREAS.md, parte E, y README.md, sección
> Presentation). Me encargo de la operación online y de la presentación. Ayúdame a comprobar la
> app online con check.py --url, a entender la demo de drift para explicarla, y a preparar
> preguntas difíciles que podría hacer el profesor sobre cada parte del sistema. El guion lo
> escribo yo; revísalo para que quepa en 6 minutos.

---

## Parte F · Bonus de aprendizaje por refuerzo (opcional, hasta +10%)

**Objetivo:** que la app aprenda de los 👍/👎. Por ejemplo, un bandit (Thompson sampling) que elige
entre tres estilos de respuesta del enrutador (breve / paso a paso / ofrecer transferencia).

**Lo que decides tú:** la recompensa y qué puede premiar sin querer (*reward hacking*), la
estrategia de exploración y su coste para los vecinos, qué parte se simula y qué parte es real,
y los riesgos. Todo esto va en la sección *Bonus* del REPORT. Lee bien el README: solo cuenta si
el bucle se cierra con feedback real.

**Prompt para Claude:**
> Estoy en el repo daiist-group-project (lee TAREAS.md, parte F, y README.md, sección Bonus).
> Quiero añadir un bandit que elija el estilo de respuesta del enrutador y aprenda de los 👍/👎
> guardados en los logs. Explícame primero las opciones (ε-greedy, UCB, Thompson) y sus costes;
> la elección, la recompensa y el análisis de riesgos los decido yo. Después ayúdame a programarlo
> sin romper check.py, y a explicar en el REPORT qué parte se aprendió de logs reales y qué
> parte con un simulador.
