"""Batuta, el orquestador: decide el orden y pasa el output de cada agente como input del siguiente.

Como un director de orquesta, no toca ningún instrumento: dirige a Iris, Euler y Vera."""
import json
import os
import re
from datetime import datetime, timezone

from . import config
from .agentes import (agente_analista, agente_comunicador, agente_recolector,
                      reiniciar_registro, resumen_tokens)

PATRON_TICKER = re.compile(r"[A-Z0-9.\-]{1,12}")

# Guardrail de gasto: análisis REALES por día en este proceso (bot en vivo o terminal).
# En GitHub Actions cada corrida empieza de cero; ahí el tope es MAX_ANALISIS_POR_RUN.
_CONTEO_DIA = {"fecha": None, "analisis": 0}


class LimiteDiarioAlcanzado(RuntimeError):
    """Se alcanzó MAX_ANALISIS_POR_DIA en modo REAL."""


def _revisar_limite_diario():
    hoy = datetime.now(timezone.utc).date().isoformat()
    if _CONTEO_DIA["fecha"] != hoy:
        _CONTEO_DIA.update(fecha=hoy, analisis=0)
    if _CONTEO_DIA["analisis"] >= config.MAX_ANALISIS_POR_DIA:
        raise LimiteDiarioAlcanzado(f"Ya van {_CONTEO_DIA['analisis']} análisis reales hoy "
                                    f"(máximo {config.MAX_ANALISIS_POR_DIA}).")
    _CONTEO_DIA["analisis"] += 1


def normalizar_ticker(texto):
    """'aapl ' → 'AAPL'. Lanza ValueError si no parece un ticker."""
    ticker = (texto or "").strip().upper()
    if not PATRON_TICKER.fullmatch(ticker):
        raise ValueError(f"Ticker no válido: '{texto}'. Ejemplo correcto: AAPL")
    return ticker


def pipeline(ticker, avisar=print, guardar=True):
    """Batuta ejecuta la cadena Iris → Euler → Vera.

    avisar: función que recibe textos de avance (print en terminal, enviar a Telegram en el bot).
    Devuelve un diccionario con las tres entregas, útil como evidencia.
    """
    ticker = normalizar_ticker(ticker)
    modo = "SIMULACIÓN" if config.MODO_SIMULACION else "REAL"
    if not config.MODO_SIMULACION:
        _revisar_limite_diario()                   # guardrail: tope de análisis reales por día
    reiniciar_registro()                           # el registro de tokens empieza en cero

    avisar(f"🎼 Batuta · Orquestador\nRecibí tu orden. Inicio la cadena para {ticker} (modo {modo}).")
    avisar(f"🛰️ Iris · Recolectora buscando datos de {ticker}…")
    ficha, herramientas = agente_recolector(ticker)
    if config.MODO_CLASE:
        avisar("📦 Entrega 1→2 · Iris → Euler (ficha):\n" + json.dumps(ficha, ensure_ascii=False, indent=1)[:1500]
               + f"\n🔧 Herramientas MCP usadas: {', '.join(herramientas) or 'ninguna'}")

    avisar("🧮 Euler · Analista calculando e interpretando…")
    analisis = agente_analista(ficha)
    if config.MODO_CLASE:
        avisar("📦 Entrega 2→3 · Euler → Vera (indicadores):\n"
               + json.dumps(analisis["indicadores"], ensure_ascii=False, indent=1))

    avisar("✍️ Vera · Comunicadora redactando la nota…")
    nota = agente_comunicador(analisis)

    resultado = {
        "ticker": ticker,
        "modo": modo,
        "fecha_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "entrega_1_ficha": ficha,
        "herramientas_mcp": herramientas,
        "entrega_2_analisis": analisis,
        "entrega_3_nota": nota,
        "registro_tokens": resumen_tokens(),
    }
    tokens = resultado["registro_tokens"]
    avisar(f"🧾 Registro de tokens: entrada {tokens['total_entrada']} · salida {tokens['total_salida']} "
           f"· total {tokens['total']} de {tokens['presupuesto']}"
           + (" (modo simulación: no se llamó a Claude)" if config.MODO_SIMULACION else ""))
    if guardar:
        resultado["archivo"] = guardar_evidencia(resultado)
    return resultado


def guardar_evidencia(resultado):
    """Guarda la corrida completa en salidas/TICKER_fecha.json (evidencia para la rúbrica)."""
    os.makedirs(config.CARPETA_SALIDAS, exist_ok=True)
    sello = resultado["fecha_utc"].replace(":", "").replace("-", "")[:15]
    ruta = os.path.join(config.CARPETA_SALIDAS, f"{resultado['ticker']}_{sello}.json")
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(resultado, archivo, ensure_ascii=False, indent=2)
    # Bitácora acumulada: una línea por análisis, fácil de sumar en Excel (salidas/registro_tokens.jsonl)
    tokens = resultado.get("registro_tokens", {})
    with open(os.path.join(config.CARPETA_SALIDAS, "registro_tokens.jsonl"), "a", encoding="utf-8") as bitacora:
        bitacora.write(json.dumps({"fecha_utc": resultado["fecha_utc"], "ticker": resultado["ticker"],
                                   "modo": resultado["modo"], "modelo": tokens.get("modelo"),
                                   "entrada": tokens.get("total_entrada", 0),
                                   "salida": tokens.get("total_salida", 0)}, ensure_ascii=False) + "\n")
    return ruta
