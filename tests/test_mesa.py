"""Pruebas en modo simulación: verifican la cadena sin llaves ni internet.  Ejecutar: pytest -q"""
import json
import os

import pytest

os.environ["MODO_SIMULACION"] = "1"

from mesa import agentes, config, pipeline as pl          # noqa: E402
from mesa import comandos                                  # noqa: E402


@pytest.fixture(autouse=True)
def simulacion(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "MODO_SIMULACION", True)
    monkeypatch.setattr(config, "CARPETA_SALIDAS", str(tmp_path))


def test_formula_posicion_rango_52_semanas():
    ind = agentes.calcular_indicadores({"precio": "250.5", "max_52s": "300", "min_52s": "200", "beta": "0.7"})
    assert ind["posicion_rango_52s_pct"] == 50.5          # (250.5-200)/(300-200)*100
    assert ind["semaforo_beta"].startswith("🟢")


@pytest.mark.parametrize("beta, color", [(0.5, "🟢"), (0.8, "🟡"), (1.2, "🟡"), (1.3, "🔴"), (None, "⚪")])
def test_semaforo_beta(beta, color):
    assert agentes.calcular_indicadores({"beta": beta})["semaforo_beta"].startswith(color)


def test_datos_faltantes_no_rompen_el_calculo():
    ind = agentes.calcular_indicadores({"precio": None, "max_52s": "100", "min_52s": "100"})
    assert ind["posicion_rango_52s_pct"] is None


def test_extraer_json_con_texto_alrededor():
    assert agentes.extraer_json('Aquí tienes: {"a": 1} listo')["a"] == 1
    with pytest.raises(ValueError):
        agentes.extraer_json("sin json")


@pytest.mark.parametrize("entrada, esperado", [(" aapl ", "AAPL"), ("brk.b", "BRK.B")])
def test_ticker_valido(entrada, esperado):
    assert pl.normalizar_ticker(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", "AAPL; rm -rf", "ACCIONMUYLARGAXYZ"])
def test_ticker_invalido(entrada):
    with pytest.raises(ValueError):
        pl.normalizar_ticker(entrada)


def test_cadena_completa_output_es_input():
    avisos = []
    r = pl.pipeline("msft", avisar=avisos.append)
    assert r["entrega_2_analisis"]["ficha"] == r["entrega_1_ficha"]       # 1 → 2
    assert r["entrega_1_ficha"]["ticker"] in r["entrega_3_nota"]          # 2 → 3
    assert agentes.DESCARGO in r["entrega_3_nota"]
    assert any("Entrega 1→2" in a for a in avisos) and any("Entrega 2→3" in a for a in avisos)
    with open(r["archivo"], encoding="utf-8") as f:
        assert json.load(f)["ticker"] == "MSFT"


def test_mcp_caido_usa_respaldo_demo(monkeypatch):
    monkeypatch.setattr(config, "MODO_SIMULACION", False)

    def falla(*args, **kwargs):
        raise ConnectionError("sin red")
    monkeypatch.setattr(agentes, "llamar_claude", falla)
    ficha, herramientas = agentes.agente_recolector("AAPL")
    assert "DEMO" in ficha["fuente"] and herramientas == []


def test_agentes_reales_encadenan_con_claude_simulado(monkeypatch):
    """Imita las respuestas de Claude para revisar el camino 'real' sin gastar llaves."""
    monkeypatch.setattr(config, "MODO_SIMULACION", False)

    def claude_falso(system, mensaje, usar_mcp=False, max_tokens=900, agente="?"):
        if usar_mcp:
            return ('{"nombre":"IBM","sector":"Tech","precio":"250.5","cambio_pct":"-0.8%",'
                    '"pe_ratio":"40.1","beta":"0.7","max_52s":"300","min_52s":"200"}', ["GLOBAL_QUOTE"])
        if "Analista" in system:
            datos = json.loads(mensaje)
            assert datos["indicadores"]["posicion_rango_52s_pct"] == 50.5   # recibió la entrega 1
            return '{"lectura_precio":"a","lectura_riesgo":"b","lectura_valuacion":"c","pregunta_para_investigar":"d"}', []
        assert '"lectura_precio": "a"' in mensaje                           # recibió la entrega 2
        return "IBM: nota sin descargo", []

    monkeypatch.setattr(agentes, "llamar_claude", claude_falso)
    r = pl.pipeline("IBM", avisar=lambda t: None)
    assert r["herramientas_mcp"] == ["GLOBAL_QUOTE"]
    assert r["entrega_1_ficha"]["fuente"] == "Alpha Vantage vía MCP"
    assert r["entrega_3_nota"].endswith(agentes.DESCARGO)                   # el descargo se garantiza


def test_bot_ignora_chats_ajenos_y_responde_ayuda(monkeypatch):
    enviados = []
    monkeypatch.setattr(comandos, "enviar", lambda chat, texto: enviados.append((chat, texto)))
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "111")
    assert comandos.atender({"chat": {"id": 999}, "text": "/analiza AAPL"}) is None
    assert enviados[-1][1] == "Este bot es privado."
    comandos.atender({"chat": {"id": 111}, "text": "hola"})
    assert "Mesa Financiera" in enviados[-1][1]
    r = comandos.atender({"chat": {"id": 111}, "text": "/analiza aapl"})
    assert r["ticker"] == "AAPL" and agentes.DESCARGO in enviados[-1][1]


def test_revision_de_github_actions_atiende_y_confirma(monkeypatch):
    """Simula la corrida de GitHub Actions: 4 mensajes pendientes, límite de 3 por revisión."""
    import revisar_telegram as rt
    pendientes = [{"update_id": i, "message": {"chat": {"id": 111}, "text": t}}
                  for i, t in enumerate(["/analiza AAPL", "hola", "/analiza MSFT", "/analiza NVDA"], start=10)]
    confirmados, enviados = [], []
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "111")
    monkeypatch.setattr(config, "MAX_ANALISIS_POR_RUN", 3)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "token-de-prueba")
    monkeypatch.setattr(rt, "verificar_bot", lambda: "bot_prueba")
    monkeypatch.setattr(rt, "preparar_polling", lambda: None)
    monkeypatch.setattr(rt, "obtener_mensajes", lambda: pendientes)
    monkeypatch.setattr(rt, "confirmar_leidos", confirmados.append)
    monkeypatch.setattr(comandos, "enviar", lambda chat, texto: enviados.append(texto))
    rt.main()
    assert confirmados == [10, 11, 12]                      # NVDA queda para la siguiente revisión
    assert sum(agentes.DESCARGO in t for t in enviados) == 2  # AAPL y MSFT recibieron su nota


def test_revision_sin_token_termina_sin_error(monkeypatch, capsys):
    """Una copia de la plantilla sin Secrets no debe marcar error en Actions cada 10 minutos."""
    import revisar_telegram as rt
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    rt.main()
    assert "nada que revisar" in capsys.readouterr().out


def test_los_agentes_se_presentan_con_su_nombre():
    """Los nombres del mockup (Batuta, Iris, Euler, Vera) aparecen en Telegram."""
    avisos = []
    r = pl.pipeline("AAPL", avisar=avisos.append)
    texto = "\n".join(avisos)
    for nombre in ("Batuta", "Iris", "Euler", "Vera"):
        assert nombre in texto
    assert r["entrega_3_nota"].startswith(agentes.FIRMA_VERA)


def test_vera_mentora_usa_analogia_con_el_numero_de_python():
    """Vera explica como mentora, pero el número de la analogía es el que calculó Python."""
    r = pl.pipeline("AAPL", avisar=lambda _: None)
    nota = r["entrega_3_nota"]
    posicion = r["entrega_2_analisis"]["indicadores"]["posicion_rango_52s_pct"]   # 50.0 con datos demo
    assert f"escalón {posicion}" in nota
    assert "Tarea para ti:" in nota
    assert nota.rstrip().endswith(agentes.DESCARGO)


# ----------------------------------------------------------------------
# Guardrails de seguridad
# ----------------------------------------------------------------------
TOKEN_FALSO = "123456:TOKEN-FALSO-DE-PRUEBA"


def test_guardrail_1_errores_de_red_no_muestran_el_token(monkeypatch):
    import requests
    from mesa import telegram_io
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", TOKEN_FALSO)

    def red_caida(verbo, url, **kwargs):
        raise requests.ConnectionError(f"Max retries exceeded with url: {url}")
    monkeypatch.setattr(telegram_io.requests, "request", red_caida)
    with pytest.raises(requests.RequestException) as error:      # el bot sigue reconociéndolo como error de red
        telegram_io.obtener_mensajes()
    assert TOKEN_FALSO not in str(error.value) and "***" in str(error.value)
    assert error.value.__suppress_context__                       # el error original (con token) no se imprime


def test_guardrail_1_ocultar_limpia_todas_las_llaves(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-falsa-123")
    monkeypatch.setattr(config, "ALPHAVANTAGE_API_KEY", "AVFALSA999")
    texto = config.ocultar("url?apikey=AVFALSA999 y llave sk-ant-falsa-123")
    assert "AVFALSA999" not in texto and "sk-ant-falsa-123" not in texto


def test_guardrail_2_sin_chat_id_el_bot_no_atiende_a_nadie(monkeypatch):
    from mesa import telegram_io
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    assert not telegram_io.chat_autorizado(111)
    enviados = []
    monkeypatch.setattr(comandos, "enviar", lambda chat, texto: enviados.append(texto))
    assert comandos.atender({"chat": {"id": 111}, "text": "/analiza AAPL"}) is None
    assert enviados == ["Este bot es privado."]


def test_guardrail_3_contar_solo_tus_analiza_pendientes(monkeypatch):
    import revisar_telegram as rt
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "111")
    pendientes = [{"update_id": 1, "message": {"chat": {"id": 111}, "text": "/analiza AAPL"}},
                  {"update_id": 2, "message": {"chat": {"id": 111}, "text": "hola"}},
                  {"update_id": 3, "message": {"chat": {"id": 999}, "text": "/analiza MSFT"}}]
    assert rt.contar_pendientes(pendientes) == 1      # ni "hola" ni el chat ajeno piden aprobación


def test_guardrail_3_contar_no_confirma_ni_responde(monkeypatch, tmp_path):
    import revisar_telegram as rt
    salida = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(salida))
    monkeypatch.setattr(rt.sys, "argv", ["revisar_telegram.py", "--contar"])
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "token-de-prueba")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "111")
    monkeypatch.setattr(rt, "verificar_bot", lambda: "bot_prueba")
    monkeypatch.setattr(rt, "preparar_polling", lambda: None)
    monkeypatch.setattr(rt, "obtener_mensajes",
                        lambda: [{"update_id": 5, "message": {"chat": {"id": 111}, "text": "/analiza AAPL"}}])
    monkeypatch.setattr(rt, "confirmar_leidos", lambda _: pytest.fail("--contar no debe confirmar"))
    monkeypatch.setattr(rt, "atender", lambda _: pytest.fail("--contar no debe responder"))
    rt.main()
    assert salida.read_text() == "pendientes=1\n"


class _Uso:
    def __init__(self, entrada, salida):
        self.input_tokens, self.output_tokens = entrada, salida


class _Respuesta:
    def __init__(self, texto, entrada, salida):
        self.content = [type("Bloque", (), {"type": "text", "text": texto})()]
        self.usage = _Uso(entrada, salida)


def test_guardrail_4_llamar_claude_registra_tokens(monkeypatch):
    cliente = type("Cliente", (), {})()
    cliente.messages = type("M", (), {"create": staticmethod(lambda **kw: _Respuesta("hola", 120, 30))})()
    monkeypatch.setattr(agentes, "_cliente_claude", lambda: cliente)
    agentes.reiniciar_registro()
    agentes.llamar_claude("sistema", "mensaje", agente="Euler")
    resumen = agentes.resumen_tokens()
    assert resumen["llamadas"] == [{"agente": "Euler", "entrada": 120, "salida": 30}]
    assert resumen["total"] == 150


def test_guardrail_4_presupuesto_excedido_detiene_la_cadena(monkeypatch):
    cliente = type("Cliente", (), {})()
    cliente.messages = type("M", (), {"create": staticmethod(lambda **kw: _Respuesta("x", 900, 200))})()
    monkeypatch.setattr(agentes, "_cliente_claude", lambda: cliente)
    monkeypatch.setattr(config, "MAX_TOKENS_POR_ANALISIS", 1000)
    agentes.reiniciar_registro()
    with pytest.raises(agentes.PresupuestoExcedido):
        agentes.llamar_claude("s", "m", agente="Vera")


def test_guardrail_4_presupuesto_no_se_disfraza_de_datos_demo(monkeypatch):
    monkeypatch.setattr(config, "MODO_SIMULACION", False)

    def caro(*args, **kwargs):
        raise agentes.PresupuestoExcedido("demasiados tokens")
    monkeypatch.setattr(agentes, "llamar_claude", caro)
    with pytest.raises(agentes.PresupuestoExcedido):
        agentes.agente_recolector("AAPL")


def test_guardrail_4_limite_diario_en_modo_real(monkeypatch):
    monkeypatch.setattr(config, "MODO_SIMULACION", False)
    monkeypatch.setattr(config, "MAX_ANALISIS_POR_DIA", 0)
    with pytest.raises(pl.LimiteDiarioAlcanzado):
        pl.pipeline("AAPL", avisar=lambda _: None)


def test_guardrail_4_evidencia_incluye_registro_de_tokens():
    avisos = []
    r = pl.pipeline("AAPL", avisar=avisos.append)
    assert r["registro_tokens"]["total"] == 0                     # simulación: no se llamó a Claude
    assert any("Registro de tokens" in a for a in avisos)
    bitacora = os.path.join(config.CARPETA_SALIDAS, "registro_tokens.jsonl")
    assert json.loads(open(bitacora, encoding="utf-8").readline())["ticker"] == "AAPL"
