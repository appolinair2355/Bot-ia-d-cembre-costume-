# ==========================================================
# card_predictor.py
# Bot de prédiction intelligent – Déployable Render
# Développeur : SOSSOU Kouamé Appolinaire
# ==========================================================

import re
import time
import os
import json
import logging
from datetime import datetime, time as dtime
from typing import Optional, Dict, Tuple, List
from collections import defaultdict

import pytz

# ==========================================================
# CONFIGURATION DES CANAUX (PRÉCONFIGURÉS)
# ==========================================================

SOURCE_CHANNEL_ID = -1002682552255
PREDICTION_CHANNEL_ID = -1003329818758

# ==========================================================
# CONFIGURATION GÉNÉRALE
# ==========================================================

BENIN_TZ = pytz.timezone("Africa/Porto-Novo")

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

def path(f): 
    return os.path.join(DATA_DIR, f)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ==========================================================
# RÈGLES STATIQUES (DÉSACTIVÉES PAR DÉFAUT)
# ==========================================================

STATIC_RULES = {
    "10♦️": "♠️", "10♠️": "❤️", "9♣️": "❤️", "9♦️": "♠️",
    "8♣️": "♠️", "8♠️": "♣️", "7♠️": "♠️", "7♣️": "♣️",
    "6♦️": "♣️", "6♣️": "♦️", "A❤️": "❤️", "5❤️": "❤️", "5♠️": "♠️"
}

SYMBOL_MAP = {0: "✅0️⃣", 1: "✅1️⃣", 2: "✅2️⃣"}

# ==========================================================
# SESSIONS DE PRÉDICTION
# ==========================================================

SESSIONS = [
    (dtime(2, 0), dtime(5, 0)),
    (dtime(15, 0), dtime(17, 0)),
    (dtime(21, 0), dtime(22, 0)),
]

# ==========================================================
# MESSAGES
# ==========================================================

def reprise_message(version: str, session: str) -> str:
    return f"""
🚀 RELANCE DES PRÉDICTIONS AUTOMATIQUES

⏳ Démarrage dans quelques instants…
🧠 Mode intelligent : ACTIVÉ

🔄 Dernière mise à jour des règles inter :
🆕 Version : {version} (🇧🇯)

📊 Session active :
⏰ {session}

👨‍💻 Développeur :
SOSSOU Kouamé Appolinaire

🔖 Version du système :
{version}
""".strip()

# ==========================================================
# CLASSE PRINCIPALE
# ==========================================================

class CardPredictor:

    def __init__(self, telegram_message_sender=None):
        self.sender = telegram_message_sender

        self.source_channel = SOURCE_CHANNEL_ID
        self.prediction_channel = PREDICTION_CHANNEL_ID

        # --- MODES ---
        self.static_enabled = False
        self.smart_enabled = True

        # --- DONNÉES ---
        self.predictions = self._load("predictions.json", {})
        self.inter_data = self._load("inter_data.json", [])
        self.smart_rules = self._load("smart_rules.json", [])
        self.rule_block = self._load("rule_block.json", {})
        self.sequential = self._load("sequential.json", {})
        self.collected = set(self._load("collected.json", []))

        self.last_inter_update = self._load("last_inter_update.json", 0)
        self.last_prediction_game = self._load("last_prediction_game.json", 0)

    # ======================================================
    # UTILITAIRES
    # ======================================================

    def now(self):
        return datetime.now(BENIN_TZ)

    def _load(self, name, default):
        try:
            with open(path(name), "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return default

    def _save(self, name, data):
        with open(path(name), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_version(self) -> str:
        if not self.last_inter_update:
            return "Base neuve"
        return datetime.fromtimestamp(
            self.last_inter_update, BENIN_TZ
        ).strftime("%Y-%m-%d | %Hh%M")

    # ======================================================
    # SESSION
    # ======================================================

    def in_session(self) -> Optional[str]:
        now = self.now().time()
        for start, end in SESSIONS:
            if start <= now < end:
                return f"{start.strftime('%Hh%M')} – {end.strftime('%Hh%M')}"
        return None

    # ======================================================
    # EXTRACTION
    # ======================================================

    def extract_game(self, text: str) -> Optional[int]:
        m = re.search(r"#N(\d+)", text)
        return int(m.group(1)) if m else None

    def extract_cards(self, text: str) -> List[str]:
        m = re.search(r"\(([^)]*)\)", text)
        if not m:
            return []
        return [
            f"{v.upper()}{c.replace('❤️','♥️')}"
            for v, c in re.findall(r"(\d+|[AKQJ])(♠️|❤️|♦️|♣️|♥️)", m.group(1))
        ]

    # ======================================================
    # COLLECTE INTER (TOUJOURS ACTIVE)
    # ======================================================

    def collect(self, game: int, text: str):
        if game in self.collected:
            return

        cards = self.extract_cards(text)
        if not cards:
            return

        self.collected.add(game)
        self.sequential[str(game)] = cards[0]

        prev = str(game - 2)
        if prev in self.sequential:
            self.inter_data.append({
                "trigger": self.sequential[prev],
                "result": cards[0][-2:]
            })
            self.recompute_rules()

        self._save("inter_data.json", self.inter_data)
        self._save("sequential.json", self.sequential)
        self._save("collected.json", list(self.collected))

    # ======================================================
    # RÈGLES INTELLIGENTES
    # ======================================================

    def recompute_rules(self):
        stats = defaultdict(lambda: defaultdict(int))
        for d in self.inter_data:
            stats[d["result"]][d["trigger"]] += 1

        rules = []
        for suit, triggers in stats.items():
            top = sorted(triggers.items(), key=lambda x: x[1], reverse=True)[:2]
            for trig, cnt in top:
                rules.append({
                    "trigger": trig,
                    "predict": suit,
                    "count": cnt
                })

        self.smart_rules = rules
        self.last_inter_update = time.time()

        self._save("smart_rules.json", rules)
        self._save("last_inter_update.json", self.last_inter_update)

    # ======================================================
    # PRÉDICTION
    # ======================================================

    def should_predict(self, game: int, text: str) -> Optional[str]:
        session = self.in_session()
        if not session or game <= self.last_prediction_game:
            return None

        cards = self.extract_cards(text)
        if not cards:
            return None

        trigger = cards[0]

        if self.smart_enabled:
            for r in self.smart_rules:
                key = f"{r['trigger']}_{r['predict']}"
                if r["trigger"] == trigger:
                    blocked = self.rule_block.get(key, 0)
                    if r["count"] > blocked:
                        return r["predict"]

        if self.static_enabled and trigger in STATIC_RULES:
            return STATIC_RULES[trigger]

        return None

    def register_prediction(self, game: int, suit: str, msg_id: int):
        self.predictions[str(game + 2)] = {
            "from": game,
            "suit": suit,
            "status": "pending",
            "msg_id": msg_id
        }
        self.last_prediction_game = game
        self._save("predictions.json", self.predictions)
        self._save("last_prediction_game.json", self.last_prediction_game)

    # ======================================================
    # VÉRIFICATION DES RÉSULTATS
    # ======================================================

    def verify(self, game: int, text: str):
        cards = self.extract_cards(text)
        if not cards:
            return None

        for g, p in self.predictions.items():
            if p["status"] != "pending":
                continue

            offset = game - int(p["from"])
            if offset < 0 or offset > 2:
                continue

            if any(c.endswith(p["suit"]) for c in cards):
                p["status"] = "won"
                if offset == 2:
                    self.block_rule(p)
                return (p, SYMBOL_MAP[offset])

            if offset == 2:
                p["status"] = "lost"
                self.block_rule(p)
                return (p, "❌")

        self._save("predictions.json", self.predictions)
        return None

    def block_rule(self, p):
        trigger = self.sequential.get(str(p["from"]))
        if not trigger:
            return
        key = f"{trigger}_{p['suit']}"
        for r in self.smart_rules:
            if r["trigger"] == trigger and r["predict"] == p["suit"]:
                self.rule_block[key] = r["count"]
        self._save("rule_block.json", self.rule_block)

    # ======================================================
    # RESET QUOTIDIEN 00h59
    # ======================================================

    def daily_reset(self):
        now = self.now().time()
        if now.hour == 0 and now.minute == 59:
            for f in os.listdir(DATA_DIR):
                os.remove(path(f))
            self.__init__(self.sender)

# ==========================================================
# INSTANCE
# ==========================================================

card_predictor = CardPredictor()
