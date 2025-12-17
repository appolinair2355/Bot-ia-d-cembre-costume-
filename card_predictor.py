# ================== card_predictor.py ==================
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

BENIN_TZ = pytz.timezone("Africa/Porto-Novo")

SYMBOL_MAP = {0: "✅0️⃣", 1: "✅1️⃣", 2: "✅2️⃣"}

PREDICTION_SESSIONS = [(2, 5), (15, 17), (21, 22)]
INTER_UPDATE_INTERVAL = 1800  # 30 minutes


class CardPredictor:
    def __init__(self, telegram_message_sender=None):
        self.telegram_message_sender = telegram_message_sender

        # Channels (configurés via /config)
        self.target_channel_id = self._load("target_channel_id.json")
        self.prediction_channel_id = self._load("prediction_channel_id.json")

        # États
        self.is_inter_mode_active = True

        # IA
        self.inter_data = self._load("inter_data.json", default=[])
        self.smart_rules = self._load("smart_rules.json", default=[])
        self.quarantined_rules = self._load("quarantined_rules.json", default={})
        self.collected_games = set(self._load("collected_games.json", default=[]))

        # Prédictions
        self.predictions = self._load("predictions.json", default={})

        # Temps
        self.last_inter_update_time = self._load("last_inter_update.json")
        self.wait_until_next_update = self._load("wait_until_next_update.json", 0)
        self.last_reset_date = self._load("last_reset_date.json")

    # ======================================================
    # CONFIGURATION DES CANAUX
    # ======================================================
    def set_channel_id(self, chat_id: int, channel_type: str):
        if channel_type == "source":
            self.target_channel_id = chat_id
            self._save("target_channel_id.json", chat_id)
        elif channel_type == "prediction":
            self.prediction_channel_id = chat_id
            self._save("prediction_channel_id.json", chat_id)

    # ======================================================
    # TEMPS & SESSIONS
    # ======================================================
    def now(self):
        return datetime.now(BENIN_TZ)

    def is_in_session(self):
        h = self.now().hour
        return any(s <= h < e for s, e in PREDICTION_SESSIONS)

    def current_session(self):
        h = self.now().hour
        for s, e in PREDICTION_SESSIONS:
            if s <= h < e:
                return s, e
        return None

    # ======================================================
    # RESET & RAPPORTS
    # ======================================================
    def check_timers(self):
        now = self.now()

        # Reset journalier
        if now.hour == 0 and now.minute == 59:
            if self.last_reset_date != now.strftime("%Y-%m-%d"):
                self.send_report("JOURNALIER")
                self.full_reset()
                self.last_reset_date = now.strftime("%Y-%m-%d")
                self._save("last_reset_date.json", self.last_reset_date)

        # Fin de session
        for s, e in PREDICTION_SESSIONS:
            if now.hour == e and now.minute == 0:
                self.send_report(f"{s:02d}h–{e:02d}h")

    def send_report(self, label):
        if not self.telegram_message_sender or not self.prediction_channel_id:
            return

        preds = list(self.predictions.values())
        total = len(preds)
        win = sum(1 for p in preds if str(p["status"]).startswith("✅"))
        lose = sum(1 for p in preds if p["status"] == "❌")
        rate = (win / total * 100) if total else 0

        msg = (
            "📊 **BILAN DE SESSION**\n\n"
            f"⏰ Session : {label} 🇧🇯\n\n"
            f"📈 Total : {total}\n"
            f"✅ Réussites : {win}\n"
            f"❌ Échecs : {lose}\n\n"
            f"📊 Taux : {rate:.2f} %\n\n"
            f"🧠 Version IA : {self.get_inter_version()}\n\n"
            "👨‍💻 Développeur :\n"
            "SOSSOU Kouamé Appolinaire"
        )

        self.telegram_message_sender(self.prediction_channel_id, msg)

    def full_reset(self):
        self.inter_data.clear()
        self.smart_rules.clear()
        self.quarantined_rules.clear()
        self.collected_games.clear()
        self.predictions.clear()
        self.last_inter_update_time = time.time()
        self.wait_until_next_update = 0
        self.save_all()

    # ======================================================
    # IA INTER – AUTO UPDATE 30 MIN
    # ======================================================
    def should_update_inter(self):
        if not self.last_inter_update_time:
            return True
        return time.time() - self.last_inter_update_time >= INTER_UPDATE_INTERVAL

    def auto_update_inter(self):
        if self.should_update_inter():
            self.analyze_and_set_smart_rules()

    def collect_inter_data(self, game, message):
        info = self.get_first_card_info(message)
        if not info or game in self.collected_games:
            return

        card, suit = info
        self.collected_games.add(game)

        self.inter_data.append({
            "trigger": card,
            "result": suit
        })

        self.save_all()

    def analyze_and_set_smart_rules(self):
        stats = defaultdict(lambda: defaultdict(int))
        for d in self.inter_data:
            stats[d["result"]][d["trigger"]] += 1

        self.smart_rules = []
        for suit, triggers in stats.items():
            for t, c in sorted(triggers.items(), key=lambda x: x[1], reverse=True)[:2]:
                self.smart_rules.append({
                    "trigger": t,
                    "predict": suit,
                    "count": c
                })

        self.last_inter_update_time = time.time()
        self.save_all()

    # ======================================================
    # PRÉDICTION
    # ======================================================
    def should_predict(self, message) -> Tuple[bool, Optional[int], Optional[str]]:
        self.check_timers()
        self.auto_update_inter()

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
                key = f"{trigger}_{r['predict']}"
                if key in self.quarantined_rules and self.quarantined_rules[key] >= r["count"]:
                    continue
                return True, game, r["predict"]

        return False, None, None

    def make_prediction(self, game, suit, msg_id):
        self.predictions[game + 2] = {
            "predicted_costume": suit,
            "status": "pending",
            "message_id": msg_id,
            "time": time.time()
        }
        self._save("predictions.json", self.predictions)

    # ======================================================
    # VÉRIFICATION
    # ======================================================
    def verify_prediction_from_edit(self, message):
        return self._verify(message)

    def _verify(self, message):
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
                status = SYMBOL_MAP[offset]
                p["status"] = status
                if status in ("❌", "✅2️⃣"):
                    self.quarantined_rules[f"{p['predicted_costume']}"] = p.get("count", 0)
                self.save_all()
                return {
                    "type": "edit_message",
                    "message_id_to_edit": p["message_id"],
                    "new_message": f"🔵{g}🔵 : {p['predicted_costume']} → {status}"
                }

        return None

    # ======================================================
    # UTILITAIRES
    # ======================================================
    def extract_game_number(self, t):
        m = re.search(r"#N(\d+)", t) or re.search(r"🔵(\d+)🔵", t)
        return int(m.group(1)) if m else None

    def get_first_card_info(self, t):
        m = re.search(r"\(([^)]*)\)", t)
        if not m:
            return None
        v, s = re.findall(r"(\d+|[AKQJ])(♠️|❤️|♦️|♣️|♥️)", m.group(1))[0]
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

    def get_inter_version(self):
        if not self.last_inter_update_time:
            return "Base neuve"
        return datetime.fromtimestamp(
            self.last_inter_update_time, BENIN_TZ
        ).strftime("%Y-%m-%d | %Hh%M")

    # ======================================================
    # SAVE / LOAD
    # ======================================================
    def _load(self, f, default=None):
        if not os.path.exists(f):
            return default
        try:
            with open(f, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except:
            return default

    def _save(self, f, d):
        with open(f, "w", encoding="utf-8") as fp:
            json.dump(d, fp, indent=2, ensure_ascii=False)

    def save_all(self):
        self._save("inter_data.json", self.inter_data)
        self._save("smart_rules.json", self.smart_rules)
        self._save("quarantined_rules.json", self.quarantined_rules)
        self._save("predictions.json", self.predictions)
        self._save("collected_games.json", list(self.collected_games))
        self._save("last_inter_update.json", self.last_inter_update_time)
        self._save("wait_until_next_update.json", self.wait_until_next_update)


# INSTANCE
card_predictor = CardPredictor()
