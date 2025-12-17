# handlers.py

import logging
import time
import json
from collections import defaultdict
from typing import Dict, Any, Optional
import requests

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Import CardPredictor
try:
    from card_predictor import CardPredictor
except ImportError:
    logger.error("❌ IMPOSSIBLE D'IMPORTER CARDPREDICTOR")
    CardPredictor = None

user_message_counts = defaultdict(list)

# ===================== MESSAGES =====================

WELCOME_MESSAGE = """
👋 **BIENVENUE SUR LE BOT ENSEIGNE !** ♠️♥️♦️♣️

🧠 Prédictions basées sur :
• Règles statiques
• Mode intelligent INTER (Top 2 par enseigne)

━━━━━━━━━━━━━━━━━━━━━
📋 **COMMANDES**
━━━━━━━━━━━━━━━━━━━━━

/start – Aide  
/stat – Statut rapide  
/etat – État complet  

/inter status – Règles INTER  
/inter activate – Activer INTER  
/inter default – Désactiver INTER  

/collect – Données collectées  
/reset – Reset prédictions  
/deploy – Package Render  

━━━━━━━━━━━━━━━━━━━━━
👨‍💻 Développeur :
SOSSOU Kouamé Appolinaire
"""

HELP_MESSAGE = """
🤖 **AIDE /INTER**
• /inter status
• /inter activate
• /inter default
"""

# ===================== HANDLERS =====================

class TelegramHandlers:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"

        if CardPredictor:
            self.card_predictor = CardPredictor(
                telegram_message_sender=self.send_message
            )
        else:
            self.card_predictor = None

    # ===================== SAFE GETTERS =====================

    def _get_source_channel_id(self):
        return getattr(self.card_predictor, "source_channel", None)

    def _get_prediction_channel_id(self):
        return getattr(self.card_predictor, "prediction_channel", None)

    # ===================== RATE LIMIT =====================

    def _check_rate_limit(self, user_id):
        now = time.time()
        user_message_counts[user_id] = [
            t for t in user_message_counts[user_id] if now - t < 60
        ]
        user_message_counts[user_id].append(now)
        return len(user_message_counts[user_id]) <= 30

    # ===================== SEND MESSAGE =====================

    def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode="Markdown",
        message_id: Optional[int] = None,
        edit=False,
        reply_markup: Optional[Dict] = None,
    ) -> Optional[int]:
        if not chat_id or not text:
            return None

        method = "editMessageText" if (message_id or edit) else "sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        if message_id:
            payload["message_id"] = message_id
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)

        try:
            r = requests.post(
                f"{self.base_url}/{method}", json=payload, timeout=10
            )
            if r.status_code == 200:
                return r.json().get("result", {}).get("message_id")
            else:
                logger.error(f"Telegram error {r.status_code}: {r.text}")
        except Exception as e:
            logger.error(f"Send message exception: {e}")
        return None

    # ===================== COMMANDES =====================

    def _handle_command_stat(self, chat_id: int):
        src = self._get_source_channel_id() or "Non défini"
        pred = self._get_prediction_channel_id() or "Non défini"
        mode = (
            "IA intelligente (INTER)"
            if self.card_predictor.is_inter_mode_active
            else "Statique"
        )

        msg = (
            "📊 **STATUS**\n\n"
            f"📥 Source (Input): `{src}`\n"
            f"📤 Prédiction (Output): `{pred}`\n"
            f"🧠 Mode: {mode}\n"
            f"🔄 Version: {self.card_predictor.get_version()} (🇧🇯)\n\n"
            "👨‍💻 SOSSOU Kouamé Appolinaire"
        )
        self.send_message(chat_id, msg)

    def _handle_command_inter(self, chat_id: int, text: str):
        if not self.card_predictor:
            return

        parts = text.lower().split()
        action = parts[1] if len(parts) > 1 else "status"

        if action == "activate":
            self.card_predictor.analyze_and_set_smart_rules(
                chat_id=chat_id, force_activate=True
            )
            self.send_message(chat_id, "✅ Mode INTER activé")

        elif action == "default":
            self.card_predictor.is_inter_mode_active = False
            self.card_predictor._save_all_data()
            self.send_message(chat_id, "❌ Mode INTER désactivé")

        else:
            msg, kb = self.card_predictor.get_inter_status()
            self.send_message(chat_id, msg, reply_markup=kb)

    # ===================== UPDATE HANDLER =====================

    def handle_update(self, update: Dict[str, Any]):
        if not self.card_predictor:
            return

        try:
            # ---------- MESSAGE NORMAL ----------
            if "message" in update and "text" in update["message"]:
                msg = update["message"]
            elif "channel_post" in update and "text" in update["channel_post"]:
                msg = update["channel_post"]
            else:
                return

            chat_id = msg["chat"]["id"]
            text = msg["text"]
            user_id = msg.get("from", {}).get("id", 0)

            if not self._check_rate_limit(user_id):
                return

            # ---------- COMMANDES ----------
            if text.startswith("/start"):
                self.send_message(chat_id, WELCOME_MESSAGE)

            elif text.startswith("/stat"):
                self._handle_command_stat(chat_id)

            elif text.startswith("/inter"):
                self._handle_command_inter(chat_id, text)

            elif text.startswith("/etat"):
                self.send_message(chat_id, self.card_predictor.get_bot_status())

            elif text.startswith("/collect"):
                self._handle_command_collect(chat_id)

            elif text.startswith("/reset"):
                self._handle_command_reset(chat_id)

            elif text.startswith("/deploy"):
                self._handle_command_deploy(chat_id)

            # ---------- CANAL SOURCE ----------
            elif str(chat_id) == str(self._get_source_channel_id()):
                game_num = self.card_predictor.extract_game_number(text)
                if game_num:
                    self.card_predictor.collect_inter_data(game_num, text)

                if self.card_predictor.has_completion_indicators(text):
                    res = self.card_predictor.verify_prediction_from_edit(text)
                    if res and res.get("edit"):
                        self.send_message(
                            self._get_prediction_channel_id(),
                            res["text"],
                            message_id=res["message_id"],
                            edit=True,
                        )

                ok, num, val = self.card_predictor.should_predict(text)
                if ok:
                    pred_text = self.card_predictor.prepare_prediction_text(num, val)
                    mid = self.send_message(
                        self._get_prediction_channel_id(), pred_text
                    )
                    if mid:
                        self.card_predictor.make_prediction(num, val, mid)

        except Exception as e:
            logger.error(f"Update error: {e}")
