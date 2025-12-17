# card_predictor.py

import re
import os
import json
import time
import logging
from datetime import datetime
from collections import defaultdict
from typing import Optional, Tuple
import pytz

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ================== CONFIG ==================
BENIN_TZ = pytz.timezone("Africa/Porto-Novo")

SYMBOL_MAP = {
    0: "✅0️⃣",  # N
    1: "✅1️⃣",  # N+1
    2: "✅2️⃣"   # N+2
}

PREDICTION_SESSIONS = [
    (2, 5),
    (5, 17),
    (17, 22)
]

# ================== CLASS ==================
class CardPredictor:
    def __init__(self, telegram_message_sender=None):
        self.telegram_message_sender = telegram_message_sender

        # Canaux
        self.HARDCODED_SOURCE_ID = None
        self.HARDCODED_PREDICTION_ID = None
        self.target_channel_id = self._load("target_channel_id.json")
        self.prediction_channel_id = self._load("prediction_channel_id.json")

        # États
        self.is_inter_mode_active = False

        # Données IA
        self.inter_data = self._load("inter_data.json", default=[])
        self.smart_rules = self._load("smart_rules.json", default=[])
        self.quarantined_rules = self._load("quarantined_rules.json", default={})
        self.collected_games = set(self._load("collected_games.json", default=[]))

        # Prédictions
        self.predictions = self._load("predictions.json", default={})

        # Temps
        self.wait_until_next_update = self._load("wait_until_next_update.json", default=0)
        self.last_inter_update_time = self._load("last_inter_update.json", default=None)
        self.last_report_sent = self._load("last_report_sent.json", default={})

    # ======================================================
    # ⏰ TEMPS & SESSIONS
    # ======================================================
    def now(self):
        return datetime.now(BENIN_TZ)

    def is_in_session(self):
        h = self.now().hour
        return any(start <= h < end for start, end in PREDICTION_SESSIONS)

    def current_session_label(self):
        h = self.now().hour
        for start, end in PREDICTION_SESSIONS:
            if start <= h < end:
                return f"{start:02d}h00 – {end:02d}h00"
        return "Hors session"

    # ======================================================
    # 📊 RAPPORTS AUTOMATIQUES
    # ======================================================
    def check_and_send_reports(self):
        if not self.telegram_message_sender or not self.prediction_channel_id:
            return

        now = self.now()
        key_date = now.strftime("%Y-%m-%d")

        report_hours = {
            5: ("02h00", "05h00"),
            17: ("05h00", "17h00"),
            22: ("17h00", "22h00")
        }

        if now.hour in report_hours and now.minute == 0:
            key = f"{key_date}_{now.hour}"
            if self.last_report_sent.get(key):
                return

            start, end = report_hours[now.hour]
            msg = self._send_session_report(start, end)
            self.telegram_message_sender(self.prediction_channel_id, msg)

            self.last_report_sent[key] = True
            self._save_all()

    def _send_session_report(self, session_start, session_end):
        total = len(self.predictions)
        wins = sum(1 for p in self.predictions.values() if str(p["status"]).startswith("✅"))
        fails = sum(1 for p in self.predictions.values() if p["status"] == "❌")
        rate = (wins / total * 100) if total else 0

        inter_time = self.get_inter_version()

        return (
            "📊 **BILAN DE SESSION**\n\n"
            f"⏰ Session : {session_start} – {session_end} (🇧🇯)\n\n"
            f"📈 Total prédictions : {total}\n"
            f"✅ Réussites : {wins}\n"
            f"❌ Échecs : {fails}\n\n"
            f"📊 Taux de réussite : {rate:.2f} %\n\n"
            f"🧠 Mode intelligent : {'ACTIVÉ' if self.is_inter_mode_active else 'DÉSACTIVÉ'}\n"
            f"🔄 Dernière mise à jour INTER : {inter_time}\n"
            f"🆕 Version : {inter_time}\n\n"
            "👨‍💻 Développeur :\n"
            "SOSSOU Kouamé Appolinaire"
        )
        # ======================================================
    # 🧠 COLLECTE & ANALYSE INTER
    # ======================================================
    def collect_inter_data(self, game_number: int, message: str):
        self.check_and_send_reports()

        info = self.get_first_card_info(message)
        if not info or game_number in self.collected_games:
            return

        card, suit = info
        self.collected_games.add(game_number)

        self.inter_data.append({
            "numero": game_number - 2,
            "declencheur": card,
            "result_suit": suit
        })

        # Mise à jour automatique toutes les 30 min
        if not self.last_inter_update_time or time.time() - self.last_inter_update_time >= 1800:
            self.analyze_and_set_smart_rules()

        self._save_all()

    def analyze_and_set_smart_rules(self, chat_id=None, force_activate=False):
        if not self.inter_data:
            return

        stats = defaultdict(lambda: defaultdict(int))
        for d in self.inter_data:
            stats[d["result_suit"]][d["declencheur"]] += 1

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
        if force_activate:
            self.is_inter_mode_active = True

        self._save_all()

    # ======================================================
    # 🎯 PRÉDICTION
    # ======================================================
    def should_predict(self, message: str) -> Tuple[bool, Optional[int], Optional[str]]:
        self.check_and_send_reports()

        if not self.is_in_session():
            return False, None, None

        if not self.is_inter_mode_active:
            return False, None, None

        if time.time() < self.wait_until_next_update:
            return False, None, None

        game = self.extract_game_number(message)
        info = self.get_first_card_info(message)
        if not game or not info:
            return False, None, None

        trigger, _ = info

        for rule in self.smart_rules:
            if rule["trigger"] == trigger:
                key = f"{trigger}_{rule['predict']}"
                if key in self.quarantined_rules and self.quarantined_rules[key] >= rule["count"]:
                    continue
                return True, game, rule["predict"]

        return False, None, None

    def make_prediction(self, game_number: int, suit: str, message_id: int):
        self.predictions[game_number + 2] = {
            "predicted_costume": suit,
            "status": "pending",
            "message_id": message_id,
            "predicted_from": game_number
        }
        self._save("predictions.json", self.predictions)

    # ======================================================
    # ✅ VÉRIFICATION (N, N+1, N+2)
    # ======================================================
    def has_completion_indicators(self, text: str):
        return any(x in text for x in ["✅", "❌", "🔰"])

    def verify_prediction_from_edit(self, message: str):
        return self._verify_prediction_common(message)

    def _verify_prediction_common(self, message: str):
        self.check_and_send_reports()

        game = self.extract_game_number(message)
        if not game:
            return None

        cards = self.get_all_cards_in_first_group(message)

        for pg, p in self.predictions.items():
            if p["status"] != "pending":
                continue

            offset = game - pg
            if offset < 0 or offset > 2:
                continue

            found = any(c.endswith(p["predicted_costume"]) for c in cards)

            if found:
                status = SYMBOL_MAP[offset]
                p["status"] = status

                if status in ("❌", "✅2️⃣"):
                    self._apply_quarantine(p)

                self._save_all()

                return {
                    "type": "edit_message",
                    "message_id_to_edit": p["message_id"],
                    "new_message": f"🔵{pg}🔵:{p['predicted_costume']} statut :{status}"
                }

            if offset == 2:
                p["status"] = "❌"
                self._apply_quarantine(p)
                self._save_all()

                return {
                    "type": "edit_message",
                    "message_id_to_edit": p["message_id"],
                    "new_message": f"🔵{pg}🔵:{p['predicted_costume']} statut :❌"
                }

        return None

    # ======================================================
    # 🚫 QUARANTAINE INTELLIGENTE
    # ======================================================
    def _apply_quarantine(self, prediction):
        trigger = None
        for r in self.smart_rules:
            if r["predict"] == prediction["predicted_costume"]:
                trigger = r["trigger"]
                rule_count = r["count"]
                break

        if not trigger:
            return

        key = f"{trigger}_{prediction['predicted_costume']}"
        self.quarantined_rules[key] = rule_count

        # Pause 30 minutes
        self.wait_until_next_update = time.time() + 1800

        self._save_all()
# ======================================================
    # 📊 STATUS & COMMANDES
    # ======================================================
    def get_bot_status(self):
        total = len(self.predictions)
        wins = sum(1 for p in self.predictions.values() if str(p["status"]).startswith("✅"))
        fails = sum(1 for p in self.predictions.values() if p["status"] == "❌")

        return (
            "📊 **STATUT DU BOT**\n\n"
            f"🧠 Mode intelligent : {'ACTIF' if self.is_inter_mode_active else 'INACTIF'}\n"
            f"🎯 Session : {self.current_session_label()}\n"
            f"📈 Prédictions : {total}\n"
            f"✅ Réussites : {wins}\n"
            f"❌ Échecs : {fails}\n\n"
            f"🔖 Version IA : {self.get_inter_version()}"
        )

    def get_inter_status(self):
        msg = "🧠 **RÈGLES INTELLIGENTES (TOP 2)**\n\n"
        by_suit = defaultdict(list)

        for r in self.smart_rules:
            by_suit[r["predict"]].append(r)

        for suit, rules in by_suit.items():
            msg += f"**{suit}**\n"
            for r in rules:
                msg += f"• {r['trigger']} ({r['count']}x)\n"
            msg += "\n"

        return msg, None

    def prepare_prediction_text(self, game_number, suit):
        return f"🔵{game_number + 2}🔵:{suit} statut :⏳"

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
    def extract_game_number(self, text):
        m = re.search(r"#N(\d+)", text) or re.search(r"🔵(\d+)🔵", text)
        return int(m.group(1)) if m else None

    def get_first_card_info(self, text):
        m = re.search(r"\(([^)]*)\)", text)
        if not m:
            return None

        cards = re.findall(r"(\d+|[AKQJ])(♠️|❤️|♦️|♣️|♥️)", m.group(1))
        if not cards:
            return None

        v, s = cards[0]
        suit = "❤️" if s in ("❤️", "♥️") else s
        return f"{v}{suit}", suit

    def get_all_cards_in_first_group(self, text):
        m = re.search(r"\(([^)]*)\)", text)
        if not m:
            return []

        return [
            f"{v}{('❤️' if s in ('❤️','♥️') else s)}"
            for v, s in re.findall(r"(\d+|[AKQJ])(♠️|❤️|♦️|♣️|♥️)", m.group(1))
        ]

    # ======================================================
    # ⚙️ CONFIG CANAUX
    # ======================================================
    def set_channel_id(self, chat_id: int, channel_type: str):
        if channel_type == "source":
            self.target_channel_id = chat_id
            self._save("target_channel_id.json", chat_id)
        elif channel_type == "prediction":
            self.prediction_channel_id = chat_id
            self._save("prediction_channel_id.json", chat_id)

    # ======================================================
    # 🔄 RESET
    # ======================================================
    def reset_automatic_predictions(self):
        removed = 0
        kept = {}

        for k, v in self.predictions.items():
            if v["status"] == "pending":
                removed += 1
            else:
                kept[k] = v

        self.predictions = kept
        self._save("predictions.json", self.predictions)

        return {
            "removed": removed,
            "kept_inter": len(kept)
        }

    # ======================================================
    # 💾 SAVE / LOAD
    # ======================================================
    def _load(self, file, default=None):
        if not os.path.exists(file):
            return default
        try:
            with open(file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
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
        self._save("last_report_sent.json", self.last_report_sent)

