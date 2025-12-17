# card_predictor.py

import re
import logging
import time
import os
import json
from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any
from collections import defaultdict

logger = logging.getLogger(__name__)
# Mis à jour à DEBUG pour vous aider à tracer la collecte.
logger.setLevel(logging.DEBUG) 

# --- 1. RÈGLES STATIQUES (13 Règles Exactes) ---
# Si la 1ère carte du jeu N est la clé -> On prédit la valeur pour N+2
STATIC_RULES = {
    "10♦️": "♠️", "10♠️": "❤️", 
    "9♣️": "❤️", "9♦️": "♠️",
    "8♣️": "♠️", "8♠️": "♣️", 
    "7♠️": "♠️", "7♣️": "♣️",
    "6♦️": "♣️", "6♣️": "♦️", 
    "A❤️": "❤️", 
    "5❤️": "❤️", "5♠️": "♠️"
}

# Symboles pour les status de vérification
SYMBOL_MAP = {0: '✅0️⃣', 1: '✅1️⃣', 2: '✅2️⃣'}

class CardPredictor:
    """Gère la logique de prédiction d'ENSEIGNE (Couleur) et la vérification."""

    def __init__(self, telegram_message_sender=None):
        
        # <<<<<<<<<<<<<<<< ZONE CRITIQUE À MODIFIER PAR L'UTILISATEUR >>>>>>>>>>>>>>>>
        # ⚠️ IDs DE CANAUX CONFIGURÉS (Par défaut si aucun fichier config n'existe)
        self.HARDCODED_SOURCE_ID = -1002682552255  
        self.HARDCODED_PREDICTION_ID = -1003341134749 
        # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>

        # --- A. Chargement de la Persistance ---
        self.predictions = self._load_data('predictions.json') 
        self.processed_messages = self._load_data('processed.json', is_set=True) 
        self.last_prediction_time = self._load_data('last_prediction_time.json', is_scalar=True) or 0
        self.last_predicted_game_number = self._load_data('last_predicted_game_number.json', is_scalar=True) or 0
        self.consecutive_fails = self._load_data('consecutive_fails.json', is_scalar=True) or 0
        self.pending_edits: Dict[int, Dict] = self._load_data('pending_edits.json')
        
        # --- B. Configuration des Canaux ---
        raw_config = self._load_data('channels_config.json')
        self.config_data = raw_config if isinstance(raw_config, dict) else {}
        
        self.target_channel_id = self.config_data.get('target_channel_id') or self.HARDCODED_SOURCE_ID
        self.prediction_channel_id = self.config_data.get('prediction_channel_id') or self.HARDCODED_PREDICTION_ID
        
        # --- C. Logique du Mode INTER ---
        self.telegram_message_sender = telegram_message_sender
        self.active_admin_chat_id = self._load_data('active_admin_chat_id.json', is_scalar=True)
        
        # Historique séquentiel pour l'apprentissage IA
        self.sequential_history: Dict[int, Dict] = self._load_data('sequential_history.json') 
        self.inter_data: List[Dict] = self._load_data('inter_data.json') 
        self.is_inter_mode_active = self._load_data('inter_mode_status.json', is_scalar=True)
        self.smart_rules = self._load_data('smart_rules.json')
        self.last_analysis_time = self._load_data('last_analysis_time.json', is_scalar=True) or 0
        self.collected_games = self._load_data('collected_games.json', is_set=True)
        
        # --- D. NOUVEAU : SYSTÈME DE QUARANTAINE ---
        self.quarantined_rules = self._load_data('quarantined_rules.json') or {}
        
        # Variables de sécurité supplémentaires de ton code original
        self.single_trigger_until = self._load_data('single_trigger_until.json', is_scalar=True) or 0
        self.consecutive_two_wins = self._load_data('consecutive_two_wins.json', is_scalar=True) or 0
        self.wait_until_next_update = self._load_data('wait_until_next_update.json', is_scalar=True) or 0
        self.last_reset_time = self._load_data('last_reset_time.json', is_scalar=True) or 0
        self.prediction_count_by_channel = self._load_data('prediction_count_by_channel.json') or {}
        
        if self.is_inter_mode_active is None:
            self.is_inter_mode_active = True
        
        self.prediction_cooldown = 30 
        
        # Analyse automatique si données présentes
        if self.inter_data and not self.is_inter_mode_active and not self.smart_rules:
             self.analyze_and_set_smart_rules(initial_load=True)

    # --- MÉTHODES DE CHARGEMENT / SAUVEGARDE (Version Longue) ---
    def _load_data(self, filename: str, is_set: bool = False, is_scalar: bool = False) -> Any:
        try:
            is_dict = filename in ['channels_config.json', 'predictions.json', 'sequential_history.json', 'smart_rules.json', 'pending_edits.json', 'quarantined_rules.json']
            if not os.path.exists(filename):
                if is_set: return set()
                if is_scalar: return None
                return {} if is_dict else []
            
            with open(filename, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    if is_set: return set()
                    if is_scalar: return None
                    return {} if is_dict else []
                data = json.loads(content)
                if is_set: return set(data)
                if filename in ['sequential_history.json', 'predictions.json', 'pending_edits.json'] and isinstance(data, dict): 
                    return {int(k): v for k, v in data.items()}
                return data
        except Exception as e:
            logger.error(f"⚠️ Erreur chargement {filename}: {e}")
            if is_set: return set()
            if is_scalar: return None
            return {} if filename.endswith('.json') else []

    def _save_data(self, data: Any, filename: str):
        try:
            if isinstance(data, set): data = list(data)
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"❌ Erreur sauvegarde {filename}: {e}")

    def _save_all_data(self):
        """Sauvegarde l'intégralité des variables d'état (Tes 20+ fichiers)"""
        self._save_data(self.predictions, 'predictions.json')
        self._save_data(self.processed_messages, 'processed.json')
        self._save_data(self.last_prediction_time, 'last_prediction_time.json')
        self._save_data(self.last_predicted_game_number, 'last_predicted_game_number.json')
        self._save_data(self.consecutive_fails, 'consecutive_fails.json')
        self._save_data(self.inter_data, 'inter_data.json')
        self._save_data(self.sequential_history, 'sequential_history.json')
        self._save_data(self.is_inter_mode_active, 'inter_mode_status.json')
        self._save_data(self.smart_rules, 'smart_rules.json')
        self._save_data(self.active_admin_chat_id, 'active_admin_chat_id.json')
        self._save_data(self.last_analysis_time, 'last_analysis_time.json')
        self._save_data(self.pending_edits, 'pending_edits.json')
        self._save_data(self.collected_games, 'collected_games.json')
        self._save_data(self.single_trigger_until, 'single_trigger_until.json')
        self._save_data(self.consecutive_two_wins, 'consecutive_two_wins.json')
        self._save_data(self.wait_until_next_update, 'wait_until_next_update.json')
        self._save_data(self.last_reset_time, 'last_reset_time.json')
        self._save_data(self.quarantined_rules, 'quarantined_rules.json')

    # --- CONFIGURATION ET PARSING (Tes Regex d'origine) ---
    def set_channel_id(self, channel_id: int, channel_type: str):
        if channel_type == 'source':
            self.target_channel_id = channel_id
            self.config_data['target_channel_id'] = channel_id
        elif channel_type == 'prediction':
            self.prediction_channel_id = channel_id
            self.config_data['prediction_channel_id'] = channel_id
        self._save_data(self.config_data, 'channels_config.json')
        return True

    def _extract_parentheses_content(self, text: str) -> List[str]:
        return re.findall(r'\(([^)]+)\)', text)

    def _count_cards_in_content(self, content: str) -> int:
        normalized_content = content.replace("❤️", "♥️")
        return len(re.findall(r'(\d+|[AKQJ])(♠️|♥️|♦️|♣️)', normalized_content, re.IGNORECASE))
        
    def has_pending_indicators(self, text: str) -> bool:
        return any(indicator in text for indicator in ['⏰', '▶', '🕐', '➡️'])

    def has_completion_indicators(self, text: str) -> bool:
        return any(indicator in text for indicator in ['✅', '❌', '🔰'])
        
    def is_final_result_structurally_valid(self, text: str) -> bool:
        matches = self._extract_parentheses_content(text)
        if len(matches) < 2: return False
        if ('#T' in text or '🔵#R' in text): return True
        if len(matches) == 2:
            c1, c2 = self._count_cards_in_content(matches[0]), self._count_cards_in_content(matches[1])
            if (c1 == 3 and c2 == 2) or (c1 == 3 and c2 == 3) or (c1 == 2 and c2 == 3): return True
        return False
        
    def extract_game_number(self, message: str) -> Optional[int]:
        match = re.search(r'#N(\d+)\.', message, re.IGNORECASE) 
        if not match: match = re.search(r'🔵(\d+)🔵', message)
        return int(match.group(1)) if match else None

    def extract_card_details(self, content: str) -> List[Tuple[str, str]]:
        normalized_content = content.replace("♥️", "❤️")
        return re.findall(r'(\d+|[AKQJ])(♠️|❤️|♦️|♣️)', normalized_content, re.IGNORECASE)

    def get_first_card_info(self, message: str) -> Optional[Tuple[str, str]]:
        match = re.search(r'\(([^)]*)\)', message)
        if not match: return None
        details = self.extract_card_details(match.group(1))
        if details:
            v, c = details[0]
            if c == "❤️": c = "♥️" 
            return f"{v.upper()}{c}", c 
        return None
    
    def get_all_cards_in_first_group(self, message: str) -> List[str]:
        match = re.search(r'\(([^)]*)\)', message)
        if not match: return []
        details = self.extract_card_details(match.group(1))
        return [f"{v.upper()}{('♥️' if c == '❤️' else c)}" for v, c in details]
        
    # --- LOGIQUE IA INTER (Tes Fonctions de collecte) ---
    def collect_inter_data(self, game_number: int, message: str):
        info = self.get_first_card_info(message)
        if not info: return
        full_card, suit = info
        result_suit_normalized = suit.replace("❤️", "♥️")
        
        if game_number in self.collected_games: return

        self.sequential_history[game_number] = {'carte': full_card, 'date': datetime.now().isoformat()}
        self.collected_games.add(game_number)
        
        n_minus_2 = game_number - 2
        trigger_entry = self.sequential_history.get(n_minus_2)
        
        if trigger_entry:
            self.inter_data.append({
                'numero_resultat': game_number,
                'declencheur': trigger_entry['carte'], 
                'numero_declencheur': n_minus_2,
                'result_suit': result_suit_normalized, 
                'date': datetime.now().isoformat()
            })
        
        limit = game_number - 50
        self.sequential_history = {k:v for k,v in self.sequential_history.items() if k >= limit}
        self.collected_games = {g for g in self.collected_games if g >= limit}
        self._save_all_data()

    def analyze_and_set_smart_rules(self, chat_id: int = None, initial_load: bool = False, force_activate: bool = False):
        result_suit_groups = defaultdict(lambda: defaultdict(int))
        for entry in self.inter_data:
            result_suit_groups[entry['result_suit']][entry['declencheur']] += 1
        
        self.smart_rules = []
        for result_suit in ['♠️', '♥️', '♦️', '♣️']:
            res_norm = "❤️" if result_suit == "♥️" else result_suit
            triggers = result_suit_groups.get(result_suit, {})
            if not triggers: continue
            top_triggers = sorted(triggers.items(), key=lambda x: x[1], reverse=True)[:2]
            for trigger_card, count in top_triggers:
                self.smart_rules.append({
                    'trigger': trigger_card, 
                    'predict': res_norm, 
                    'count': count, 
                    'result_suit': res_norm
                })
        
        if force_activate: self.is_inter_mode_active = True
        elif self.smart_rules: self.is_inter_mode_active = True
            
        self.last_analysis_time = time.time()
        self._save_all_data()
        if chat_id and self.telegram_message_sender:
            msg = f"✅ IA Analysée : {len(self.smart_rules)} règles générées." if self.smart_rules else "⚠️ Pas assez de données."
            self.telegram_message_sender(chat_id, msg)

    def check_and_update_rules(self):
        if time.time() - self.last_analysis_time > 1800:
            self.analyze_and_set_smart_rules(chat_id=self.active_admin_chat_id)

    def get_inter_status(self) -> Tuple[str, Dict]:
        data_count = len(self.inter_data)
        rules_by_result = defaultdict(list)
        for rule in self.smart_rules: rules_by_result[rule['result_suit']].append(rule)
        
        message = f"🧠 **MODE INTER - {'✅ ACTIF' if self.is_inter_mode_active else '❌ INACTIF'}**\n\n"
        message += f"📊 **{len(self.smart_rules)} règles actives** ({data_count} jeux en base):\n\n"
        for suit in ['♠️', '❤️', '♦️', '♣️']:
            if suit in rules_by_result:
                message += f"**Pour prédire {suit}:**\n"
                for rule in rules_by_result[suit]: message += f"  • {rule['trigger']} (trouvé {rule['count']}x)\n"
        
        kb = [[{'text': '🔄 Analyser maintenant', 'callback_data': 'inter_apply'}], [{'text': '❌ Désactiver IA', 'callback_data': 'inter_default'}]]
        return message, {'inline_keyboard': kb}

    # --- LOGIQUE DE PRÉDICTION AVEC QUARANTAINE ---
    def should_predict(self, message: str) -> Tuple[bool, Optional[int], Optional[str]]:
        self.check_and_update_rules()
        game_number = self.extract_game_number(message)
        if not game_number: return False, None, None
        
        # Respect de la pause sécurité
        if self.wait_until_next_update > time.time(): return False, None, None
        if self.last_predicted_game_number and (game_number - self.last_predicted_game_number < 3): return False, None, None
            
        info = self.get_first_card_info(message)
        if not info: return False, None, None
        first_card, _ = info 
        predicted_suit = None

        # 1. Vérification Mode IA
        if self.is_inter_mode_active and self.smart_rules:
            for rule in self.smart_rules:
                if rule['trigger'] == first_card:
                    rule_key = f"{first_card}_{rule['predict']}"
                    # FILTRE QUARANTAINE
                    if rule_key in self.quarantined_rules:
                        if rule['count'] <= self.quarantined_rules[rule_key]: continue
                    predicted_suit = rule['predict']
                    break
            
        # 2. Vérification Mode Statique (Si IA n'a rien trouvé)
        if not predicted_suit and first_card in STATIC_RULES:
            predicted_suit = STATIC_RULES[first_card]

        if predicted_suit:
            if time.time() < self.last_prediction_time + self.prediction_cooldown: return False, None, None
            return True, game_number, predicted_suit
        return False, None, None

    def prepare_prediction_text(self, game_number_source: int, predicted_costume: str) -> str:
        return f"🔵{game_number_source + 2}🔵:{predicted_costume} statut :⏳"

    def make_prediction(self, game_number_source: int, suit: str, message_id_bot: int):
        self.predictions[game_number_source + 2] = {
            'predicted_costume': suit, 'status': 'pending', 'predicted_from': game_number_source, 
            'message_id': message_id_bot, 'is_inter': self.is_inter_mode_active
        }
        self.last_prediction_time, self.last_predicted_game_number = time.time(), game_number_source
        self._save_all_data()

    def check_costume_in_first_parentheses(self, message: str, predicted_costume: str) -> bool:
        all_cards = self.get_all_cards_in_first_group(message)
        normalized_costume = predicted_costume.replace("❤️", "♥️")
        return any(card.endswith(normalized_costume) for card in all_cards)

    # --- VÉRIFICATION TOLÉRANCE ZÉRO (Modification demandée) ---
    def _verify_prediction_common(self, message: str, is_edited: bool = False) -> Optional[Dict]:
        game_number = self.extract_game_number(message)
        if not game_number or not self.is_final_result_structurally_valid(message): return None
        
        verification_result = None
        for predicted_game in sorted(self.predictions.keys()):
            prediction = self.predictions[predicted_game]
            if prediction.get('status') != 'pending': continue
            offset = game_number - predicted_game
            if offset < 0 or offset > 5: continue

            predicted_suit = prediction.get('predicted_costume')
            found = self.check_costume_in_first_parentheses(message, predicted_suit)
            
            # --- CAS GAGNÉ ---
            if found and offset <= 2:
                symbol = SYMBOL_MAP.get(offset, f"✅{offset}️⃣")
                prediction['status'] = 'won'
                
                # MODIFICATION : SI GAGNÉ AU PALIER 2 (✅2️⃣) -> QUARANTAINE
                if offset == 2:
                    self._apply_quarantine(prediction, "Gagné limite (✅2️⃣)")
                
                verification_result = {
                    'type': 'edit_message', 
                    'new_message': f"🔵{predicted_game}🔵:{predicted_suit} statut :{symbol}", 
                    'message_id_to_edit': prediction.get('message_id')
                }
                break 

            # --- CAS PERDU ---
            elif offset >= 2 and not found:
                prediction['status'] = 'lost'
                
                # MODIFICATION : SI PERDU (❌) -> QUARANTAINE IMMÉDIATE
                self._apply_quarantine(prediction, "Perte (❌)")
                
                verification_result = {
                    'type': 'edit_message', 
                    'new_message': f"🔵{predicted_game}🔵:{predicted_suit} statut :❌", 
                    'message_id_to_edit': prediction.get('message_id')
                }
                break 

        self._save_all_data()
        return verification_result

    def _apply_quarantine(self, prediction: Dict, reason: str):
        """Bloque la règle spécifiée immédiatement."""
        trigger = self.sequential_history.get(prediction['predicted_from'], {}).get('carte')
        suit = prediction['predicted_costume']
        if trigger:
            rule_key = f"{trigger}_{suit}"
            # On blacklist la règle avec son poids actuel
            current_count = next((r['count'] for r in self.smart_rules if r['trigger'] == trigger and r['predict'] == suit), 0)
            self.quarantined_rules[rule_key] = current_count
            logger.warning(f"🚫 QUARANTAINE ACTIVÉE : {rule_key} ({reason})")
        
        # Pause générale de 45 minutes pour le bot par sécurité
        self.wait_until_next_update = time.time() + 2700 

    # --- STATISTIQUES ET RESET (Tes dernières 150 lignes) ---
    def get_bot_status(self) -> str:
        all_p = self.predictions.values()
        total = len(all_p)
        won = sum(1 for p in all_p if p['status'] == 'won')
        lost = sum(1 for p in all_p if p['status'] == 'lost')
        pending = sum(1 for p in all_p if p['status'] == 'pending')
        
        mode = "IA (INTER) ✅" if self.is_inter_mode_active else "STATIQUE ⚙️"
        
        msg = f"""📊 **RAPPORT DÉTAILLÉ DU BOT**
        
━━━━━━━━━━━━━━━━━━━━━
🧠 **MODE ACTUEL** : {mode}
🛡️ **QUARANTAINE** : {len(self.quarantined_rules)} règles bannies
━━━━━━━━━━━━━━━━━━━━━

📈 **BILAN PRÉDICTIONS**
• Total : {total}
• Succès ✅ : {won}
• Échecs ❌ : {lost}
• En cours ⏳ : {pending}

📁 **DONNÉES IA**
• Jeux en base : {len(self.inter_data)}
• Règles apprises : {len(self.smart_rules)}
━━━━━━━━━━━━━━━━━━━━━"""
        return msg

    def reset_automatic_predictions(self) -> Dict:
        """Nettoyage de 00h59 (Heure Bénin)"""
        self.predictions = {k:v for k,v in self.predictions.items() if v.get('is_inter')}
        self.last_predicted_game_number = 0
        self.consecutive_fails = 0
        self.consecutive_two_wins = 0
        self._save_all_data()
        return {'status': 'success', 'message': 'Reset quotidien effectué'}

# Instance globale
card_predictor = CardPredictor()
