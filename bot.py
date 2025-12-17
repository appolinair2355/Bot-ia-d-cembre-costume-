"""
Telegram Bot implementation with advanced features and deployment capabilities
Version optimisée pour l'intégration APScheduler et les prédictions intelligentes.
"""
import os
import logging
import requests
import json
from typing import Dict, Any, Optional

# Importation des classes de logique métier
from handlers import TelegramHandlers

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class TelegramBot:
    """
    Classe de haut niveau pour gérer les interactions avec l'API Telegram.
    """

    def __init__(self, token: str):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        
        # Initialisation des handlers
        self.handlers = TelegramHandlers(token)
        
        # ACCÈS DIRECT AU PRÉDICTEUR
        # On expose le predictor pour que main.py puisse l'utiliser (ex: bot.predictor)
        if hasattr(self.handlers, 'card_predictor'):
            self.predictor = self.handlers.card_predictor
            logger.info("✅ Moteur de prédiction lié au Bot avec succès.")
        else:
            self.predictor = None
            logger.error("🚨 Le moteur de prédiction n'a pas pu être récupéré depuis les handlers.")

    def handle_update(self, update: Dict[str, Any]) -> None:
        """Traite les mises à jour entrantes via Webhook"""
        try:
            # Logs de suivi des activités
            if 'message' in update or 'channel_post' in update:
                logger.info(f"🔄 Bot traite un nouveau message/post")
            elif 'edited_message' in update or 'edited_channel_post' in update:
                logger.info(f"🔄 Bot traite une modification")
            
            # Délégation du traitement complet aux handlers (vérification, prédiction, etc.)
            self.handlers.handle_update(update)
            
        except Exception as e:
            logger.error(f"❌ Erreur lors du traitement de l'update : {e}")

    def send_message(self, chat_id: int, text: str, parse_mode: str = 'Markdown') -> bool:
        """
        Envoie un message textuel.
        Utilisée par APScheduler dans main.py pour les messages de session.
        """
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': parse_mode
            }
            response = requests.post(url, json=payload, timeout=10)
            return response.json().get('ok', False)
        except Exception as e:
            logger.error(f"❌ Erreur send_message : {e}")
            return False

    def set_webhook(self, webhook_url: str) -> bool:
        """Configure l'URL du Webhook auprès de Telegram"""
        try:
            url = f"{self.base_url}/setWebhook"
            data = {
                'url': webhook_url,
                'allowed_updates': [
                    'message', 
                    'edited_message', 
                    'channel_post', 
                    'edited_channel_post', 
                    'callback_query', 
                    'my_chat_member'
                ]
            }
            response = requests.post(url, json=data, timeout=10)
            result = response.json()
            if result.get('ok'):
                logger.info(f"✅ Webhook configuré avec succès : {webhook_url}")
                return True
            else:
                logger.error(f"❌ Échec configuration webhook : {result}")
                return False
        except Exception as e:
            logger.error(f"❌ Erreur critique set_webhook : {e}")
            return False

    # --- Méthodes utilitaires ---
    
    def get_bot_info(self) -> Dict[str, Any]:
        """Récupère les informations du bot (getMe)"""
        try:
            url = f"{self.base_url}/getMe"
            response = requests.get(url, timeout=30)
            return response.json().get('result', {}) if response.json().get('ok') else {}
        except Exception as e:
            logger.error(f"Error getting bot info: {e}")
            return {}
