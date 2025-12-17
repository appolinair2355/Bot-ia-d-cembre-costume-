# card_predictor.py
import re
import os
import json
import time
import logging
from datetime import datetime
from collections import defaultdict
import pytz
from typing import Optional, Tuple

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ================== CONFIG ==================
BENIN_TZ = pytz.timezone("Africa/Porto-Novo")

SYMBOL_MAP = {0: "✅0️⃣", 1: "✅1️⃣", 2: "✅2️⃣"}

PREDICTION_SESSIONS = [
    (2, 5),
    (15, 17),
    (21, 22)
]

SESSION_END_HOURS = [5, 17, 22]

INTER_UPDATE_INTERVAL = 1800  # 30 minutes

# ================== CLASS ==================
class CardPredictor:
    def __init__(self, telegram_message_sender=None):
        self.telegram_message_sender = telegram_message_sender

        # 🔒 CANAUX (JAMAIS RESET)
        self.target_channel_id = self._load("target_channel_id.json")
        self.prediction_channel_id = self._load("prediction_channel_id.json")

        # États
        self.is_inter_mode_active = True

        # IA DATA
        self.inter_data = self._load("inter_data.json", [])
        self.smart_rules = self._load("smart_rules.json", [])
        self.quarantined_rules = self._load("quarantined_rules.json", {})
        self.collected_games = set(self._load("collected_games.json", []))

        # Predictions
        self.predictions = self._load("predictions.json", {})

        # Timing
        self.wait_until_next_update = self._load("wait_until_next_update.json", 0)
        self.last_inter_update_time = self._load("last_inter_update.json")
        self.last_reset_date = self._load("last_reset_date.json")
        self.last_session_report = self._load("last_session_report.json")

    # ======================================================
    # ⏰ TIME
    # ======================================================
    def now(self):
        return datetime.now(BENIN_TZ)

    def is_in_session(self):
        h = self.now().hour
        return any(start <= h < end for start, end in PREDICTION_SESSIONS)

    def current_session(self):
        h = self.now().hour
        for start, end in PREDICTION_SESSIONS:
            if start <= h < end:
                return start, end
        return None, None

    # ======================================================
    # 🔄 INTER AUTO UPDATE (30min)
    # ======================================================
    def auto_update_inter_rules(self):
        if not self.inter_data:
            return
        if self.last_inter_update_time and time.time() - self.last_inter_update_time < INTER_UPDATE_INTERVAL:
            return
        self.analyze_and_set_smart_rules()

    # ======================================================
    # 📊 FIN DE SESSION AUTO
    # ======================================================
    def check_session_end_report(self):
        now = self.now()
        if now.minute != 0 or now.hour not in SESSION_END_HOURS:
            return

        key = f"{now.date()}_{now.hour}"
        if self.last_session_report == key:
            return

        start, end = None, None
        for s, e in PREDICTION_SESSIONS:
            if e == now.hour:
                start, end = s, e

        if start is None:
            return

        self._send_session_report(start, end)
        self.last_session_report = key
        self._save("last_session_report.json", key)

    def _send_session_report(self, start, end):
        if not self.telegram_message_sender or not self.prediction_channel_id:
            return

        preds = list(self.predictions.values())
        total = len(preds)
        won = sum(1 for p in preds if str(p["status"]).startswith("✅"))
        lost = sum(1 for p in preds if p["status"] == "❌")
        rate = (won / total * 100) if total else 0

        msg = (
            "📊 **BILAN DE SESSION**\n\n"
            f"⏰ Session : {start:02d}h00 – {end:02d}h00 (🇧🇯)\n\n"
            f"📈 Total prédictions : {total}\n"
            f"✅ Réussites : {won}\n"
            f"❌ Échecs : {lost}\n\n"
            f"📊 Taux de réussite : {rate:.2f} %\n\n"
            f"🧠 Mode intelligent : ACTIVÉ\n"
            f"🔄 Dernière mise à jour INTER : {self.get_inter_version()}\n\n"
            "👨‍💻 Développeur :\n"
            "SOSSOU Kouamé Appolinaire"
        )

        self.telegram_message_sender(self.prediction_channel_id, msg)

    # ======================================================
    # 🧠 INTER LOGIC
    # ======================================================
    def collect_inter_data(self, game_number: int, message: str):
        info = self.get_first_card_info(message)
        if not info or game_number in self.collected_games:
            return

        card, suit = info
        self.collected_games.add(game_number)

        self.inter_data.append({
            "numero": game_number - 2,
            "trigger": card,
            "suit": suit
        })

        self.auto_update_inter_rules()
        self._save_all()

    def analyze_and_set_smart_rules(self):
        stats = defaultdict(lambda: defaultdict(int))
        for d in self.inter_data:
            stats[d["suit"]][d["trigger"]] += 1

        rules = []
        for suit, triggers in stats.items():
            for trigger, count in sorted(triggers.items(), key=lambda x: x[1], reverse=True)[:2]:
                rules.append({
                    "trigger": trigger,
                    "predict": suit,
                    "count": count
                })

        self.smart_rules = rules
        self.last_inter_update_time = time.time()
        self._save_all()

    # ======================================================
    # 🎯 PREDICTION
    # ======================================================
    def should_predict(self, message: str) -> Tuple[bool, Optional[int], Optional[str]]:
        self.auto_update_inter_rules()
        self.check_session_end_report()

        if not self.is_in_session():
            return False, None, None

        if time.time() < self.wait_until_next_update:
            return False, None, None

        game = self.extract_game_number(message)
        info = self.get_first_card_info(message)
        if not game or not info:
            return False, None, None

        trigger, _ = info

        for r in self.smart_rules:
            if r["trigger"] == trigger:
                return True, game, r["predict"]

        return False, None, None

    def make_prediction(self, game_number: int, suit: str, message_id: int):
        self.predictions[game_number + 2] = {
            "predicted_costume": suit,
            "status": "pending",
            "message_id": message_id
        }
        self._save("predictions.json", self.predictions)

    # ======================================================
    # ✅ VERIFICATION
    # ======================================================
    def verify_prediction_from_edit(self, message: str):
        game = self.extract_game_number(message)
        if not game:
            return None

        cards = self.get_all_cards_in_first_group(message)

        for g, p in self.predictions.items():
            if p["status"] != "pending":
                continue

            offset = game - g
            if offset < 0 or offset > 2:
                continue

            if any(c.endswith(p["predicted_costume"]) for c in cards):
                p["status"] = SYMBOL_MAP[offset]
                if p["status"] in ("❌", "✅2️⃣"):
                    self.wait_until_next_update = time.time() + INTER_UPDATE_INTERVAL
                self._save_all()
                return {
                    "type": "edit_message",
                    "message_id_to_edit": p["message_id"],
                    "new_message": f"🔵{g}🔵 : {p['predicted_costume']} → {p['status']}"
                }

            if offset == 2:
                p["status"] = "❌"
                self.wait_until_next_update = time.time() + INTER_UPDATE_INTERVAL
                self._save_all()
                return {
                    "type": "edit_message",
                    "message_id_to_edit": p["message_id"],
                    "new_message": f"🔵{g}🔵 : {p['predicted_costume']} → ❌"
                }

        return None

    # ======================================================
    # 📊 STATUS
    # ======================================================
    def get_bot_status(self):
        total = len(self.predictions)
        won = sum(1 for p in self.predictions.values() if str(p["status"]).startswith("✅"))
        lost = sum(1 for p in self.predictions.values() if p["status"] == "❌")

        return (
            "📊 STATUS\n"
            f"Source (Input): {'OK' if self.target_channel_id else 'Non défini'}\n"
            f"Prédiction (Output): {'OK' if self.prediction_channel_id else 'Non défini'}\n"
            "Mode: IA\n\n"
            f"Total: {total}\n"
            f"Gagnés: {won}\n"
            f"Perdus: {lost}\n"
            f"Version: {self.get_inter_version()}"
        )

    # ======================================================
    # 🔖 VERSION
    # ======================================================
    def get_inter_version(self):
        if not self.last_inter_update_time:
            return "Base neuve"
        return datetime.fromtimestamp(
            self.last_inter_update_time,
            BENIN_TZ
        ).strftime("%Y-%m-%d | %Hh%M")

    # ======================================================
    # 🧰 UTILS
    # ======================================================
    def extract_game_number(self, t):
        m = re.search(r"#N(\d+)", t) or re.search(r"🔵(\d+)🔵", t)
        return int(m.group(1)) if m else None

    def get_first_card_info(self, t):
        m = re.search(r"\(([^)]*)\)", t)
        if not m:
            return None
        cards = re.findall(r"(\d+|[AKQJ])(♠️|❤️|♦️|♣️|♥️)", m.group(1))
        if not cards:
            return None
        v, s = cards[0]
        suit = "❤️" if s in ("❤️", "♥️") else s
        return f"{v}{suit}", suit

    def get_all_cards_in_first_group(self, t):
        m = re.search(r"\(([^)]*)\)", t)
        if not m:
            return []
        return [
            f"{v}{('❤️' if s in ('❤️','♥️') else s)}"
            for v, s in re.findall(r"(\d+|[AKQJ])(♠️|❤️|♦️|♣️|♥️)", m.group(1))
        ]

    # ======================================================
    # 💾 SAVE / LOAD
    # ======================================================
    def _load(self, file, default=None):
        if not os.path.exists(file):
            return default
        try:
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default

    def _save(self, file, data):
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _save_all(self):
        self._save("inter_data.json", self.inter_data)
        self._save("smart_rules.json", self.smart_rules)
        self._save("quarantined_rules.json", self.quarantined_rules)
        self._save("predictions.json", self.predictions)
        self._save("collected_games.json", list(self.collected_games))
        self._save("wait_until_next_update.json", self.wait_until_next_update)
        self._save("last_inter_update.json", self.last_inter_update_time)
