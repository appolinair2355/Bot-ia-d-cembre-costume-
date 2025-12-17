
"""
Configuration centralisée pour le bot compteur de cartes
"""

# ========== CONFIGURATION DES CANAUX ==========

# Canal source (où le bot lit les messages de cartes)
# Format: ID numérique du canal Telegram
STAT_CHANNEL_ID = -1002682552255  # Canal source configuré

# Canal d'affichage (où le bot envoie les compteurs et bilans)
# Format: ID numérique du canal Telegram
DISPLAY_CHANNEL_ID = -1003329818758  # Canal d'affichage configuré

# ========== CONFIGURATION DU BOT ==========

# Intervalle pour les bilans automatiques (en minutes)
# Le bot enverra un bilan à chaque heure pile (XX:00)
AUTO_BILAN_INTERVAL = 60  # 60 minutes = bilans horaires

# Port du serveur web (pour health checks)
# Port 10000 pour Replit, Port 10000 pour Render.com
DEFAULT_PORT = 8000

# ========== NOTES D'UTILISATION ==========

"""
Pour configurer les canaux:

1. Obtenir l'ID du canal source:
   - Ajoutez @userinfobot au canal
   - Notez l'ID (format: -100xxxxxxxxxx)
   - Remplacez STAT_CHANNEL_ID ci-dessus

2. Obtenir l'ID du canal d'affichage:
   - Même procédure avec @userinfobot
   - Remplacez DISPLAY_CHANNEL_ID ci-dessus

3. Le bot doit être membre des deux canaux avec permissions:
   - Lecture des messages (canal source)
   - Envoi de messages (canal d'affichage)

4. Après déploiement, vous pouvez aussi utiliser les commandes:
   /set_stat [ID] - Configurer le canal source
   /set_display [ID] - Configurer le canal d'affichage
"""
