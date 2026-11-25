"""
Component A: the call-router agent (Gemini with tools), a stand-in for Moysi's "Marina".

It reads what the caller said and decides, using two tools over data/municipio.json:
the call category (one of Moysi's 16), the department and extension, and the action:
  guiar           - a procedure agent can guide the caller step by step
  transferir      - transfer to the department's extension
  persona         - send to a human operator (asks for a person, unclear, emergency)
  fuera_de_ambito - not a town-hall matter; say so and where to go
plus a short reply to the caller in Spanish.

Every answer is cached in cache/component_a.jsonl (keyed by model, prompt version and
input), so the evaluation, the reference set and the drift demo do not spend the free
Gemini quota twice. Delete an entry to call the model again.
"""

import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MUNICIPIO = json.loads((ROOT / "data" / "municipio.json").read_text(encoding="utf-8"))
CATEGORIES = list(MUNICIPIO["categorias"])
ACTIONS = ["guiar", "transferir", "persona", "fuera_de_ambito"]
CACHE_FILE = ROOT / "cache" / "component_a.jsonl"

MODEL = "gemini-3.5-flash-lite"  # same model as assignment 3; Flash-Lite has the largest free daily quota
PROMPT_VERSION = "router-prompt-v1"
MAX_TOOL_ROUNDS = 3
# Paid-tier list price, € per million tokens (input, output). VERIFY against
# https://ai.google.dev/gemini-api/docs/pricing before quoting it in REPORT.md.
PRICE_EUR_PER_M = {"input": 0.09, "output": 0.37}

SYSTEM_PROMPT = f"""Eres la operadora telefónica automática del Ayuntamiento de {MUNICIPIO['municipio']}.
Recibes la transcripción de lo que dice un vecino al llamar. Tu trabajo es ENRUTAR la llamada, no resolverla.

Pasos:
1. Elige la categoría de la llamada. Solo valen estas: {json.dumps(CATEGORIES, ensure_ascii=False)}.
2. Llama a `info_categoria` con esa categoría para saber el departamento, su extensión y los trámites que se pueden guiar.
   Si dudas entre dos categorías, consulta las dos. Usa `buscar_tramite` si el vecino describe un trámite concreto.
3. Decide la acción:
   - "guiar": hay un trámite guiable que encaja claramente con lo que pide.
   - "transferir": es un asunto del ayuntamiento pero no hay trámite guiable; pasa la llamada al departamento.
   - "persona": pide hablar con una persona o con alguien concreto, es una urgencia, o no se entiende lo que quiere.
   - "fuera_de_ambito": no es competencia del ayuntamiento (DNI, Seguridad Social, Hacienda, DGT, médico...). Usa la categoría "Otro".
4. Escribe una respuesta corta (máximo 40 palabras), en español, de tú a usted, como se le hablaría por teléfono.
   No inventes plazos, precios ni documentos que no te den las herramientas.
   Si hay peligro para personas, di que llame al 112.

Responde SOLO con un objeto JSON, sin texto alrededor, con estas claves:
{{"categoria": str, "departamento": str, "extension": str, "accion": str, "tramite": str o null,
  "confianza": número entre 0 y 1 (lo seguro que estás de la categoría), "respuesta": str}}"""

_lock = threading.Lock()


# --- Tools -------------------------------------------------------------------

def info_categoria(categoria: str) -> dict:
    """Departamento, extensión y trámites guiables de una categoría de llamada.

    Args:
        categoria: una de las 16 categorías de llamada.
    """
    info = MUNICIPIO["categorias"].get(categoria)
    if info is None:
        return {"error": f"Categoría desconocida. Usa una de: {CATEGORIES}"}
    dept = info["departamento"]
    tramites = [{"slug": t["slug"], "nombre": t["nombre"], "guiable": t["guiable"]}
                for t in MUNICIPIO["tramites"] if t["categoria"] == categoria]
    return {"categoria": categoria, "descripcion": info["descripcion"], "departamento": dept,
            "extension": MUNICIPIO["departamentos"][dept], "horario": MUNICIPIO["horario"], "tramites": tramites}


def buscar_tramite(consulta: str) -> list[dict]:
    """Busca trámites del ayuntamiento por palabras clave y devuelve los tres que más se parecen.

    Args:
        consulta: lo que quiere hacer el vecino, con sus palabras.
    """
    words = {w for w in re.findall(r"\w+", consulta.lower()) if len(w) > 3}
    scored = []
    for t in MUNICIPIO["tramites"]:
        text = f"{t['nombre']} {t['resumen']}".lower()
        score = sum(w in text for w in words)
        if score:
            scored.append((score, t))
    scored.sort(key=lambda s: -s[0])
    return [{"slug": t["slug"], "nombre": t["nombre"], "categoria": t["categoria"], "guiable": t["guiable"], "resumen": t["resumen"]}
            for _, t in scored[:3]]


TOOLS = {"info_categoria": info_categoria, "buscar_tramite": buscar_tramite}


# --- Cache -------------------------------------------------------------------

def _key(text: str) -> str:
    return hashlib.sha256(f"{MODEL}|{PROMPT_VERSION}|{text.strip()}".encode()).hexdigest()[:24]


def _read_cache() -> dict:
    if not CACHE_FILE.is_file():
        return {}
    cache = {}
    for line in CACHE_FILE.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            cache[row["key"]] = row["output"]
        except (json.JSONDecodeError, KeyError):
            continue
    return cache


def _write_cache(key: str, output: dict) -> None:
    with _lock:
        CACHE_FILE.parent.mkdir(exist_ok=True)
        with CACHE_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": key, "output": output}, ensure_ascii=False) + "\n")


# --- The agent -----------------------------------------------------------------

def _loads_lenient(raw: str) -> dict:
    """json.loads, tolerating the odd bad escape (e.g. a broken \\u sequence) the model sometimes writes."""
    try:
        return json.loads(raw, strict=False)
    except json.JSONDecodeError:
        fixed = re.sub(r"\\u(?![0-9a-fA-F]{4})", "u", raw)
        fixed = re.sub(r'\\(?!["\\/bfnrtu])', "", fixed)
        try:
            return json.loads(fixed, strict=False)
        except json.JSONDecodeError:  # last resort: pull the fields out one by one
            fields = dict(re.findall(r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.)*)"', raw))
            if conf := re.search(r'"confianza"\s*:\s*([0-9.]+)', raw):
                fields["confianza"] = conf.group(1)
            return fields


def _parse(text: str) -> dict:
    match = re.search(r"\{.*\}", text or "", re.S)
    data = _loads_lenient(match.group(0)) if match else {}
    category = data.get("categoria") if data.get("categoria") in CATEGORIES else "Otro"
    action = data.get("accion") if data.get("accion") in ACTIONS else "persona"
    dept = data.get("departamento") or MUNICIPIO["categorias"][category]["departamento"]
    try:
        confidence = min(max(float(data.get("confianza", 0.0)), 0.0), 1.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "category": category,
        "department": dept,
        "extension": str(data.get("extension") or MUNICIPIO["departamentos"].get(dept, "301")),
        "action": action,
        "procedure": data.get("tramite"),
        "self_confidence": round(confidence, 3),
        "reply": str(data.get("respuesta") or ""),
        "parsed": bool(match),
    }


RETRY_WAITS_S = (2, 5, 15, 30, 60)  # waits before retrying a 503 (model overloaded) or 429 (rate limit)


def _generate(client, contents, config):
    for wait in (*RETRY_WAITS_S, None):
        try:
            return client.models.generate_content(model=MODEL, contents=contents, config=config)
        except Exception as error:  # noqa: BLE001
            transient = any(code in str(error)[:20] for code in ("503", "429", "500"))
            if wait is None or not transient:
                raise
            time.sleep(wait)


def _call_gemini(text: str) -> dict:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        tools=list(TOOLS.values()),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0,
    )
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=f"Transcripción del vecino: «{text}»")])]
    tokens_in = tokens_out = 0
    tool_calls = []
    # The last round forbids tools, so the model has to give its answer instead of searching again.
    final_config = config.model_copy(update={"tool_config": types.ToolConfig(
        function_calling_config=types.FunctionCallingConfig(mode="NONE"))})
    for round_ in range(MAX_TOOL_ROUNDS + 1):
        response = _generate(client, contents, final_config if round_ == MAX_TOOL_ROUNDS else config)
        usage = response.usage_metadata
        tokens_in += (usage.prompt_token_count or 0) if usage else 0
        tokens_out += ((usage.candidates_token_count or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)) if usage else 0
        if not response.function_calls:
            break
        contents.append(response.candidates[0].content)
        parts = []
        for call in response.function_calls:
            fn = TOOLS.get(call.name)
            result = fn(**(call.args or {})) if fn else {"error": "unknown tool"}
            tool_calls.append({"tool": call.name, "args": dict(call.args or {})})
            parts.append(types.Part.from_function_response(name=call.name, response={"result": result}))
        contents.append(types.Content(role="user", parts=parts))
    output = _parse(response.text)
    output["tool_calls"] = tool_calls
    output["tokens"] = tokens_in + tokens_out
    output["cost_eur"] = round(tokens_in / 1e6 * PRICE_EUR_PER_M["input"] + tokens_out / 1e6 * PRICE_EUR_PER_M["output"], 6)
    return output


def route(text: str, use_cache: bool = True) -> dict:
    """Component A's decision for one call. Never raises: on an API error it sends the call to a person."""
    key = _key(text)
    if use_cache and (hit := _read_cache().get(key)):
        return hit | {"cached": True}
    started = time.perf_counter()
    try:
        output = _call_gemini(text)
    except Exception as error:  # noqa: BLE001 - quota, network, bad key: degrade, don't crash the app
        return {"category": "Otro", "department": "Atención al Ciudadano y Registro", "extension": "301",
                "action": "persona", "procedure": None, "self_confidence": 0.0,
                "reply": "Le paso con una persona del ayuntamiento.", "parsed": False, "tool_calls": [],
                "tokens": 0, "cost_eur": 0.0, "error": f"{type(error).__name__}: {str(error)[:200]}", "cached": False}
    output["model_latency_s"] = round(time.perf_counter() - started, 3)
    _write_cache(key, output)
    return output | {"cached": False}
