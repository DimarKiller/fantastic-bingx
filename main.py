import discord
import time
import hmac
import hashlib
import os
import aiohttp
from discord.ext import tasks
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv
import json

# Cargar variables de entorno
load_dotenv()


class BingXBot:

    def __init__(self):
        # Configuración desde variables de entorno
        self.DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
        self.CHANNEL_ID = int(os.getenv('CHANNEL_ID', '0'))
        self.API_KEY = os.getenv('BINGX_API_KEY')
        self.SECRET_KEY = os.getenv('BINGX_SECRET_KEY')
        self.BASE_URL = "https://open-api.bingx.com"

        # Validación de configuración
        if not all([
                self.DISCORD_TOKEN, self.CHANNEL_ID, self.API_KEY,
                self.SECRET_KEY
        ]):
            raise ValueError("Faltan variables de entorno requeridas")

        # Configuración de Discord
        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True  # Agregar este intent
        self.client = discord.Client(intents=intents)

        # Registro de eventos
        self.client.event(self.on_ready)
        self.client.event(self.on_message)

        # Cache para evitar duplicados
        self.processed_trades = set()

        # Sesión de aiohttp
        self.session = None

    def sign_request(self, params: Dict[str, Any]) -> str:
        try:
            params = {k: str(v) for k, v in params.items()}
            query_string = '&'.join(
                [f"{key}={params[key]}" for key in sorted(params.keys())])
            signature = hmac.new(self.SECRET_KEY.encode('utf-8'),
                                 query_string.encode('utf-8'),
                                 hashlib.sha256).hexdigest()
            return signature
        except Exception as e:
            print(f"Error al firmar la solicitud: {e}")
            return ""

    async def make_request(self, endpoint: str,
                           params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Método unificado para hacer peticiones a la API"""
        try:
            if self.session is None:
                self.session = aiohttp.ClientSession()

            params["timestamp"] = str(int(time.time() * 1000))
            params["sign"] = self.sign_request(params)

            url = f"{self.BASE_URL}/{endpoint}"
            print(f"Haciendo petición a: {url}")  # Debug
            print(f"Parámetros (sin sign): {params}")  # Debug

            headers = {"X-BX-APIKEY": self.API_KEY}
            async with self.session.get(url, params=params,
                                        headers=headers) as response:
                text = await response.text()
                print(f"Respuesta de {endpoint}: {text}")  # Debug

                if response.status == 200:
                    return json.loads(text)
                else:
                    print(f"Error en la API {url}: {response.status} - {text}")
                    return None
        except Exception as e:
            print(f"Error en la petición a {endpoint}: {e}")
            print(f"Detalles del error: {str(e)}")  # Debug adicional
            return None

    async def get_recent_trades(self) -> Optional[Dict[str, Any]]:
        """Obtiene las operaciones recientes de futuros"""
        params = {
            "symbol": "BTC-USDT",
            "orderId": "",
            "startTime": str(int((time.time() - 3600) * 1000)),  # Última hora
            "endTime": str(int(time.time() * 1000)),
            "limit": "50"
        }
        return await self.make_request("openApi/swap/v2/trade/openOrders",
                                       params)

    def format_trade_message(self, trade: Dict[str, Any]) -> str:
        """Formatea el mensaje de la operación"""
        return (
            f"🔄 **Nueva operación de futuros detectada:**\n"
            f"📊 **Símbolo:** {trade.get('symbol', 'N/A')}\n"
            f"💰 **Precio:** {trade.get('price', 'N/A')}\n"
            f"📈 **Cantidad:** {trade.get('quantity', 'N/A')}\n"
            f"📍 **Tipo:** {trade.get('type', 'N/A')}\n"
            f"🎯 **Dirección:** {'Long' if trade.get('side') == 'BUY' else 'Short'}\n"
            f"⏰ **Tiempo:** <t:{int(int(trade.get('time', time.time()))/1000)}:F>\n"
        )

    @tasks.loop(seconds=30)
    async def fetch_trades(self):
        """Tarea periódica para obtener y enviar operaciones"""
        try:
            channel = self.client.get_channel(self.CHANNEL_ID)
            if not channel:
                print(f"No se pudo encontrar el canal {self.CHANNEL_ID}")
                return

            response = await self.get_recent_trades()
            if not response or "data" not in response:
                return

            trades = response["data"].get("orderList", [])
            for trade in trades:
                trade_id = trade.get('orderId')
                if trade_id and trade_id not in self.processed_trades:
                    self.processed_trades.add(trade_id)
                    await channel.send(self.format_trade_message(trade))

            # Limitar el tamaño del cache
            if len(self.processed_trades) > 1000:
                self.processed_trades = set(
                    list(self.processed_trades)[-1000:])

        except Exception as e:
            print(f"Error en fetch_trades: {e}")

    async def on_ready(self):
        """Evento cuando el bot está listo"""
        print(f"Bot conectado como {self.client.user}")
        self.fetch_trades.start()

    async def on_message(self, message):
        print(f"Mensaje recibido: {message.content}")  # Debug

        if message.author == self.client.user:  # Evitar que el bot responda a sí mismo
            return

        if message.content.startswith("!ping"):
            print("Comando ping detectado")  # Debug
            await message.channel.send("Pong!")

        elif message.content.startswith("!positions"):
            print("Comando positions detectado")  # Debug
            positions = await self.get_positions()
            print(f"Respuesta de positions: {positions}")  # Debug

            if positions and "data" in positions:
                if not positions["data"]:  # Si data está vacío
                    await message.channel.send("No hay posiciones abiertas")
                    return

                for pos in positions["data"]:
                    print(f"Procesando posición: {pos}")  # Debug
                    if abs(float(pos.get('positionAmt', '0'))) > 0:
                        await message.channel.send(
                            self.format_trade_message(pos, "position"))
            else:
                await message.channel.send(
                    "Error al obtener posiciones o no hay datos")

        elif message.content.startswith("!tpsl"):
            print("Comando tpsl detectado")  # Debug
            tp_sl = await self.get_tp_sl_orders()
            print(f"Respuesta de tp_sl: {tp_sl}")  # Debug

            if tp_sl and "data" in tp_sl:
                if not tp_sl["data"]:  # Si data está vacío
                    await message.channel.send("No hay órdenes TP/SL activas")
                    return

                for order in tp_sl["data"]:
                    print(f"Procesando TP/SL: {order}")  # Debug
                    await message.channel.send(
                        self.format_trade_message(order, "tp_sl"))
            else:
                await message.channel.send(
                    "Error al obtener órdenes TP/SL o no hay datos")

    async def cleanup(self):
        """Limpia los recursos antes de cerrar"""
        if self.session:
            await self.session.close()

    def run(self):
        """Inicia el bot"""
        try:
            self.client.run(self.DISCORD_TOKEN)
        finally:
            if self.session:
                import asyncio
                asyncio.run(self.cleanup())

    async def get_positions(self) -> Optional[Dict[str, Any]]:
        """Obtiene las posiciones abiertas"""
        params = {"symbol": "BTC-USDT"}
        return await self.make_request("openApi/swap/v2/user/positions",
                                       params)

    async def get_tp_sl_orders(self) -> Optional[Dict[str, Any]]:
        """Obtiene las órdenes TP/SL activas"""
        params = {"symbol": "BTC-USDT"}
        return await self.make_request("openApi/swap/v2/user/orders", params)


if __name__ == "__main__":
    try:
        bot = BingXBot()
        bot.run()
    except Exception as e:
        print(f"Error al iniciar el bot: {e}")
