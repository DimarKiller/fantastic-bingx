import discord
import requests
import time
import hmac
import hashlib
import json
import os
from discord.ext import tasks
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

class BingXBot:
    def __init__(self):
        # Configuración desde variables de entorno
        self.DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
        self.CHANNEL_ID = int(os.getenv('CHANNEL_ID', '0'))
        self.API_KEY = os.getenv('BINGX_API_KEY')
        self.SECRET_KEY = os.getenv('BINGX_SECRET_KEY')
        self.BASE_URL = "https://api.bingx.com/api/v1"
        
        # Validación de configuración
        if not all([self.DISCORD_TOKEN, self.CHANNEL_ID, self.API_KEY, self.SECRET_KEY]):
            raise ValueError("Faltan variables de entorno requeridas")

        # Configuración de Discord
        intents = discord.Intents.default()
        self.client = discord.Client(intents=intents)
        
        # Registro de eventos
        self.client.event(self.on_ready)
        
        # Cache para evitar duplicados
        self.processed_trades = set()

    def sign_request(self, params: Dict[str, Any]) -> str:
        """
        Firma la solicitud para la API de BingX
        """
        try:
            query_string = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
            return hmac.new(
                self.SECRET_KEY.encode(),
                query_string.encode(),
                hashlib.sha256
            ).hexdigest()
        except Exception as e:
            print(f"Error al firmar la solicitud: {e}")
            return ""

    async def get_recent_trades(self) -> Optional[Dict[str, Any]]:
        """
        Obtiene las operaciones recientes de BingX con manejo de errores
        """
        try:
            timestamp = int(time.time() * 1000)
            params = {
                "apiKey": self.API_KEY,
                "timestamp": timestamp,
            }
            params["sign"] = self.sign_request(params)
            
            async with requests.Session() as session:
                async with session.get(f"{self.BASE_URL}/order/list", params=params) as response:
                    if response.status_code == 200:
                        return await response.json()
                    else:
                        print(f"Error en la API: {response.status_code} - {await response.text()}")
                        return None
        except Exception as e:
            print(f"Error al obtener operaciones: {e}")
            return None

    def format_trade_message(self, trade: Dict[str, Any]) -> str:
        """
        Formatea el mensaje de la operación
        """
        return (
            f"🛒 **Nueva operación detectada:**\n"
            f" - **ID:** {trade.get('id', 'N/A')}\n"
            f" - **Símbolo:** {trade.get('symbol', 'N/A')}\n"
            f" - **Precio:** {trade.get('price', 'N/A')}\n"
            f" - **Cantidad:** {trade.get('quantity', 'N/A')}\n"
            f" - **Dirección:** {'Long' if trade.get('side') == 'buy' else 'Short'}\n"
            f" - **Estado:** {trade.get('status', 'N/A')}\n"
            f" - **Tiempo:** <t:{int(trade.get('time', time.time())/1000)}:F>\n"
        )

    @tasks.loop(seconds=30)  # Aumentado a 30 segundos para evitar límites de rate
    async def fetch_trades(self):
        """
        Tarea periódica para obtener y enviar operaciones
        """
        try:
            channel = self.client.get_channel(self.CHANNEL_ID)
            if not channel:
                print(f"No se pudo encontrar el canal {self.CHANNEL_ID}")
                return

            trades = await self.get_recent_trades()
            if not trades or "data" not in trades:
                return

            for trade in trades["data"]:
                trade_id = trade.get('id')
                if trade_id and trade_id not in self.processed_trades:
                    self.processed_trades.add(trade_id)
                    await channel.send(self.format_trade_message(trade))

            # Limitar el tamaño del cache
            if len(self.processed_trades) > 1000:
                self.processed_trades = set(list(self.processed_trades)[-1000:])

        except Exception as e:
            print(f"Error en fetch_trades: {e}")

    async def on_ready(self):
        """
        Evento cuando el bot está listo
        """
        print(f"Bot conectado como {self.client.user}")
        self.fetch_trades.start()

    def run(self):
        """
        Inicia el bot
        """
        self.client.run(self.DISCORD_TOKEN)

if __name__ == "__main__":
    try:
        bot = BingXBot()
        bot.run()
    except Exception as e:
        print(f"Error al iniciar el bot: {e}")
