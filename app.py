"""
The app: an App tab and a Monitoring tab. `uv run python app.py`

Keep the logic in pipeline.py (or your own modules); this file only wires it to
the interface and the logs. Keep `serve()` and the `/run` endpoint: check.py
calls `serve()` locally and `/run` on your deployed app, with one input from
eval/cases.csv (text, or a file path).
"""

import os
import time

import gradio as gr

import env
import logbook
import monitor
import pipeline

env.load_env()
LOG_TARGET = logbook.start()

TITLE = "Auditor de llamadas · Ayuntamiento de Valdeolmo"
DESCRIPTION = (
    "Para la persona que supervisa la atención telefónica: un agente de IA enruta cada llamada "
    "(componente A) y un modelo de ML la audita después (componente B). Solo se revisan a mano las "
    "llamadas en las que el auditor desconfía. *Municipio ficticio; no escriba nombres, teléfonos ni DNI.*"
)

EXAMPLES = [
    "Hola, me acabo de mudar al pueblo y me han dicho que tengo que empadronarme",
    "Hay una farola fundida en mi calle desde hace una semana",
    "Quiero abrir una peluquería en un local de la calle principal, ¿qué tengo que hacer?",
    "Me ha llegado el recibo del IBI dos veces",
    "Quiero hablar con una persona, no con una máquina",
    "Quería renovar el DNI que se me caduca",
]

ACTION_LABELS = {"guiar": "Guiar el trámite paso a paso", "transferir": "Transferir al departamento",
                 "persona": "Pasar a una persona", "fuera_de_ambito": "Fuera de ámbito (no es del ayuntamiento)"}


def serve(raw_input: str) -> dict:
    """Run one request through the pipeline, log it, and return the logged record."""
    started = time.perf_counter()
    result = pipeline.run(raw_input)
    return logbook.log_request(result | {"latency_s": round(time.perf_counter() - started, 3)})


# --- App tab -----------------------------------------------------------------

def _card_a(a: dict) -> str:
    lines = [
        "### 🤖 Decisión del enrutador (A)",
        f"**Categoría:** {a['category']}",
        f"**Departamento:** {a['department']} (ext. {a['extension']})",
        f"**Acción:** {ACTION_LABELS.get(a['action'], a['action'])}",
    ]
    if a.get("procedure"):
        lines.append(f"**Trámite:** {a['procedure']}")
    lines.append(f"**Respuesta al vecino:** _{a['reply']}_")
    if a.get("error"):
        lines.append(f"⚠️ El modelo no respondió ({a['error'][:80]}); se pasa a una persona.")
    return "\n\n".join(lines)


def _card_b(b: dict) -> str:
    top3 = "\n".join(f"- {c}: {p:.0%}" for c, p in b["top3"].items())
    return "\n\n".join([
        "### 🔍 Auditor ML (B)",
        f"**¿De acuerdo con A?** {'Sí ✅' if b['agrees'] else 'No ❌'}",
        f"**Probabilidad de que A acierte:** {b['p_a_category']:.0%}",
        f"**Categoría según el auditor:** {b['category']} ({b['confidence']:.0%})",
        f"**Top 3:**\n{top3}",
    ])


def on_run(raw_input):
    if raw_input is None or not str(raw_input).strip():
        raise gr.Error("Escriba o elija primero lo que dijo el vecino.")
    record = serve(raw_input)
    outputs = record["outputs"]
    status = ("⚠️ **Enviada a revisión humana:** el auditor no confía en el enrutado." if record["review"]
              else "✅ **Validada automáticamente.**")
    return (
        _card_a(outputs["component_a"]),
        _card_b(outputs["component_b"]),
        f"{status}  Latencia {record['latency_s']} s · {record['tokens']} tokens · {record['cost_eur']:.5f} €",
        record["id"],
    )


def on_feedback(request_id, value):
    if not request_id:
        gr.Warning("Audite primero una llamada.")
        return
    logbook.log_feedback(request_id, value)
    gr.Info("Gracias por la valoración.")


# --- Monitoring tab ----------------------------------------------------------

def on_refresh():
    logs = logbook.load()
    reference = monitor.load_reference()
    fired = monitor.alerts(logs, reference) if not logs.empty else []
    if reference is None:
        alert_text = "No reference set yet: run `uv run python main.py reference` and commit `monitoring/`."
    elif fired:
        alert_text = "### 🚨 Alertas\n" + "\n".join(f"- {message}" for message in fired)
    else:
        alert_text = "### ✅ Sin alertas"
    if reference is not None and len(logs) >= monitor.MIN_WINDOW:
        drift_table = monitor.drift(reference, monitor.live_features(logs))
    else:
        drift_table = monitor.drift(reference, reference.head(0)) if reference is not None else None
    return alert_text, monitor.summary(logs), monitor.quality(logs), drift_table, monitor.by_category(logs)


with gr.Blocks(title=TITLE) as demo:
    gr.Markdown(f"# {TITLE}\n{DESCRIPTION}")
    if missing := env.missing():
        gr.Markdown(f"⚠️ **Missing environment variables:** {', '.join(missing)}. See SETUP.md.")

    with gr.Tab("App"):
        request_id = gr.State("")
        example = gr.Dropdown(EXAMPLES, label="Ejemplos de llamada", value=None)
        raw_input = gr.Textbox(label="Lo que dijo el vecino (transcripción)", lines=4)
        run_button = gr.Button("Auditar llamada", variant="primary")
        with gr.Row():
            out_a = gr.Markdown()
            out_b = gr.Markdown()
        status = gr.Markdown()
        with gr.Row():
            up = gr.Button("👍 Bien enrutada")
            down = gr.Button("👎 Mal enrutada")
        example.change(lambda e: e, example, raw_input, api_name=False)
        run_button.click(on_run, raw_input, [out_a, out_b, status, request_id], api_name="run")
        up.click(lambda rid: on_feedback(rid, +1), request_id, None, api_name=False)
        down.click(lambda rid: on_feedback(rid, -1), request_id, None, api_name=False)

    with gr.Tab("Monitoring"):
        refresh = gr.Button("Refresh")
        alert_box = gr.Markdown()
        summary_table = gr.Dataframe(label="Summary", interactive=False)
        quality_plot = gr.LinePlot(x="time", y="value", color="signal", label="Quality over time", height=300)
        drift_table = gr.Dataframe(label=f"Drift: PSI of the last {monitor.WINDOW} requests against the reference set", interactive=False)
        category_plot = gr.BarPlot(x="category", y="calls", color="reviewed", label="Calls by router category", height=300)
        gr.Markdown(f"<small>{LOG_TARGET}</small>")
        outputs = [alert_box, summary_table, quality_plot, drift_table, category_plot]
        refresh.click(on_refresh, None, outputs, api_name=False)
        demo.load(on_refresh, None, outputs, api_name=False)


if __name__ == "__main__":
    # Render gives the port in $PORT; locally it is 7860.
    demo.launch(server_name="0.0.0.0", server_port=int(os.environ.get("PORT", 7860)))
