"""Revisión única de mensajes pendientes. Lo ejecuta GitHub Actions en horario bursátil.

No necesita tu computadora encendida: lee los /analiza que escribiste en Telegram,
corre la cadena de agentes para cada uno, responde y termina.

  python revisar_telegram.py            → atiende los mensajes pendientes
  python revisar_telegram.py --contar   → solo CUENTA tus /analiza pendientes, sin leerlos ni
                                          responder (lo usa el paso "decidir" del workflow para
                                          pedir aprobación humana solo cuando hay trabajo real)
"""
import os
import sys

from mesa import config
from mesa.comandos import atender, es_analisis
from mesa.telegram_io import (chat_autorizado, confirmar_leidos, obtener_mensajes,
                              preparar_polling, verificar_bot)


def contar_pendientes(pendientes):
    """Cuántos /analiza de TU chat esperan respuesta (los de chats ajenos no cuentan)."""
    total = 0
    for actualizacion in pendientes:
        mensaje = actualizacion.get("message") or {}
        if chat_autorizado(mensaje.get("chat", {}).get("id")) and es_analisis(mensaje.get("text")):
            total += 1
    return total


def escribir_salida_actions(nombre, valor):
    """Publica un dato para los siguientes pasos de GitHub Actions (si corre ahí)."""
    archivo = os.environ.get("GITHUB_OUTPUT")
    if archivo:
        with open(archivo, "a", encoding="utf-8") as salida:
            salida.write(f"{nombre}={valor}\n")


def main():
    solo_contar = "--contar" in sys.argv
    print("Configuración:", config.resumen())
    if not config.TELEGRAM_BOT_TOKEN:
        # Copia de la plantilla sin Secrets: terminar en verde, sin correos de error.
        print("ℹ️ Sin TELEGRAM_BOT_TOKEN: nada que revisar. Agrega tus Secrets para activar el bot.")
        escribir_salida_actions("pendientes", 0)
        return
    try:
        print(f"Bot: @{verificar_bot()}")
    except Exception as error:
        sys.exit(config.ocultar(f"❌ {error}"))

    preparar_polling()
    pendientes = obtener_mensajes()

    if solo_contar:                                          # no confirma nada: solo mira
        total = contar_pendientes(pendientes)
        print(f"🔢 /analiza pendientes de tu chat: {total}")
        escribir_salida_actions("pendientes", total)
        return

    if not pendientes:
        print("📭 No hay mensajes nuevos. Fin.")
        return

    lote = pendientes[:config.MAX_ANALISIS_POR_RUN]          # el resto queda para la siguiente revisión
    print(f"📬 {len(pendientes)} mensaje(s) pendiente(s); se atenderán {len(lote)} en esta revisión.")
    for actualizacion in lote:
        mensaje = actualizacion.get("message")
        try:
            if mensaje:
                resultado = atender(mensaje)
                if resultado:
                    print(f"✅ {resultado['ticker']} atendido · evidencia: {resultado['archivo']}")
        except Exception as error:                           # un error no detiene a los demás
            print(config.ocultar(
                f"⚠️ Error con el mensaje {actualizacion['update_id']}: {type(error).__name__}: {error}"))
        finally:
            confirmar_leidos(actualizacion["update_id"])      # nunca se procesa dos veces


if __name__ == "__main__":
    main()
