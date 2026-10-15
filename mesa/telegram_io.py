"""Comunicación con Telegram mediante la Bot API (solo peticiones HTTP, sin librerías extra).

Guardrails de seguridad:
  · El token viaja dentro de la URL; si la conexión falla, el error se limpia (config.ocultar)
    antes de que llegue a la terminal, a un log o a un chat.
  · El bot falla "cerrado": sin TELEGRAM_CHAT_ID no atiende a nadie.
"""
import requests

from . import config

LIMITE_MENSAJE = 4000          # Telegram acepta hasta 4096 caracteres por mensaje


class ErrorTelegram(requests.RequestException):
    """Error de red con Telegram cuyo mensaje ya no contiene el token."""


def _url(metodo):
    if not config.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Falta TELEGRAM_BOT_TOKEN (créalo con @BotFather).")
    return f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/{metodo}"


def _pedir(verbo, metodo, **kwargs):
    """Hace la petición HTTP y limpia el token de cualquier error de red."""
    try:
        return requests.request(verbo, _url(metodo), **kwargs).json()
    except requests.RequestException as error:
        # "from None" evita que Python imprima el error original, que sí trae la URL con el token
        raise ErrorTelegram(config.ocultar(f"{type(error).__name__}: {error}")) from None


def enviar(chat_id, texto):
    datos = _pedir("POST", "sendMessage",
                   data={"chat_id": chat_id, "text": config.ocultar(texto)[:LIMITE_MENSAJE]}, timeout=20)
    if not datos.get("ok"):
        raise RuntimeError(f"Telegram rechazó el mensaje: {datos.get('description')}")
    return datos


def verificar_bot():
    """Devuelve el @usuario del bot o lanza un error claro si el token es inválido."""
    datos = _pedir("GET", "getMe", timeout=20)
    if not datos.get("ok"):
        raise RuntimeError("Token de Telegram inválido. Revísalo con @BotFather.")
    return datos["result"]["username"]


def preparar_polling():
    """Quita un webhook previo; si existe, getUpdates no funciona."""
    _pedir("GET", "deleteWebhook", timeout=20)


def obtener_mensajes(offset=None, espera=0):
    """Mensajes pendientes. Telegram los guarda hasta 24 h si nadie los lee."""
    parametros = {"timeout": espera}
    if offset is not None:
        parametros["offset"] = offset
    datos = _pedir("GET", "getUpdates", params=parametros, timeout=espera + 15)
    if not datos.get("ok"):
        raise RuntimeError(f"getUpdates falló: {datos.get('description')}")
    return datos["result"]


def confirmar_leidos(ultimo_update_id):
    """Marca como leídos todos los mensajes hasta ese id, para no procesarlos dos veces."""
    obtener_mensajes(offset=ultimo_update_id + 1)


def chat_autorizado(chat_id):
    """Falla cerrado: solo TU chat puede usar el bot. Sin TELEGRAM_CHAT_ID no atiende a nadie."""
    return bool(config.TELEGRAM_CHAT_ID) and str(chat_id) == config.TELEGRAM_CHAT_ID
