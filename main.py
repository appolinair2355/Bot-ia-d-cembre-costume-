"""
Main entry point for the Telegram bot deployment on render.com
Optimisé avec APScheduler pour la gestion des horaires du Bénin.
"""
import os
import json
import logging
from flask import Flask, request, jsonify
import requests
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# Importe la configuration et le bot
from config import Config
from bot import TelegramBot 

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize bot and config
try:
    config = Config()
except ValueError as e:
    logger.error(f"❌ Erreur d'initialisation de la configuration: {e}")
    exit(1) 

# Initialisation du bot
bot = TelegramBot(config.BOT_TOKEN) 

# Initialize Flask app
app = Flask(__name__)

# --- FONCTIONS DE PLANIFICATION (APScheduler) ---

def job_start_session():
    """Envoie le message de reprise des prédictions"""
    msg = "🚀 **Les prédictions automatiques reprennent, mode intelligent activé**"
    # On utilise l'ID de prédiction défini dans le bot ou la config
    bot.send_message(bot.predictor.HARDCODED_PREDICTION_ID, msg, parse_mode="Markdown")
    logger.info("📢 Message de début de session envoyé.")

def job_end_session():
    """Envoie les règles de sécurité en fin de session"""
    msg = (
        "1️⃣ **LES HEURES DE JEUX FAVORABLES** : 02h à 05h / 15h à 17h / 21h à 22h\n\n"
        "2️⃣ **ÉVITEZ DE PARIER LE WEEK-END** : Le Bookmaker change régulièrement les algorithmes.\n\n"
        "3️⃣ **SUIVRE LE TIMING DES 10 MINUTES** : Après avoir gagné, sortez du jeu et revenez 10 min après.\n\n"
        "4️⃣ **NE PAS FAIRE PLUS DE 20 PARIS GAGNANTS** : Risque de blocage de compte.\n\n"
        "5️⃣ **ÉVITEZ D'ENREGISTRER UN COUPON** : Cela augmente vos chances de perdre.\n\n"
        "🍾 **BON GAINS** 🍾"
    )
    bot.send_message(bot.predictor.HARDCODED_PREDICTION_ID, msg, parse_mode="Markdown")
    logger.info("📢 Message des règles de sécurité envoyé.")

def reset_daily_data():
    """Réinitialisation programmée à 00h59 heure du Bénin."""
    try:
        # Appelle la méthode de reset dans votre CardPredictor
        if hasattr(bot, 'predictor'):
            bot.predictor.processed_messages.clear()
            # Nettoyage du fichier predictions.json comme dans votre version précédente
            predictions_file = 'predictions.json'
            if os.path.exists(predictions_file):
                with open(predictions_file, 'w') as f:
                    json.dump({}, f)
            logger.info("🔄 Réinitialisation complète de 00h59 effectuée.")
    except Exception as e:
        logger.error(f"❌ Erreur lors du reset quotidien: {e}")

def setup_scheduler():
    """Configure toutes les tâches automatiques selon l'heure du Bénin."""
    try:
        scheduler = BackgroundScheduler()
        benin_tz = pytz.timezone('Africa/Porto-Novo')

        # 1. REPRISE DES PRÉDICTIONS (02h, 15h, 21h)
        scheduler.add_job(
            job_start_session,
            CronTrigger(hour='2,15,21', minute=0, timezone=benin_tz),
            name='Debut de session'
        )

        # 2. FIN DE SESSION / RÈGLES DE SÉCURITÉ (05h, 17h, 22h)
        # Note: On les envoie à l'heure pile de la fin
        scheduler.add_job(
            job_end_session,
            CronTrigger(hour='5,17,22', minute=0, timezone=benin_tz),
            name='Fin de session'
        )

        # 3. RESET QUOTIDIEN (00h59)
        scheduler.add_job(
            reset_daily_data,
            CronTrigger(hour=0, minute=59, timezone=benin_tz),
            name='Reset quotidien'
        )

        scheduler.start()
        logger.info("⏰ Planificateur APScheduler démarré (Fuseau: Bénin)")
        return scheduler
    except Exception as e:
        logger.error(f"❌ Erreur configuration planificateur: {e}")
        return None

# --- ROUTES FLASK ---

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json(silent=True)
        if update:
            bot.handle_update(update)
        return 'OK', 200
    except Exception as e:
        logger.error(f"Error handling webhook: {e}")
        return 'Error', 500

@app.route('/health', methods=['GET'])
def health_check():
    return {'status': 'healthy'}, 200

@app.route('/', methods=['GET'])
def home():
    return {'message': 'Bot is running', 'status': 'active'}, 200

# --- INITIALISATION ---

def setup_webhook():
    try:
        full_webhook_url = config.get_webhook_url()
        if full_webhook_url:
            if bot.set_webhook(full_webhook_url):
                logger.info(f"✅ Webhook configuré: {full_webhook_url}")
    except Exception as e:
        logger.error(f"❌ Erreur setup webhook: {e}")

# Lancement des configurations
setup_webhook()
scheduler = setup_scheduler()

if __name__ == '__main__':
    port = config.PORT
    app.run(host='0.0.0.0', port=port, debug=config.DEBUG)
                   
