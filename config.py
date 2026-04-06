import os

IS_HEROKU = os.environ.get("DYNO") is not None

if IS_HEROKU:
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")
    GROUP_CHAT_ID = os.environ.get("GROUP_CHAT_ID", "")
    ORANGE_EMAIL = os.environ.get("ORANGE_EMAIL", "")
    ORANGE_PASSWORD = os.environ.get("ORANGE_PASSWORD", "")
    MAX_ERRORS = int(os.environ.get("MAX_ERRORS", "10"))
    CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "5"))
else:
    BOT_TOKEN = "8628633464:AAFNgIb1dm5JN07za8tq9Iyctmh33OUg7nU"
    ADMIN_CHAT_ID = "8339856952"
    GROUP_CHAT_ID = "-1003695775205"
    ORANGE_EMAIL = "tawandamahachi07@gmail.com"
    ORANGE_PASSWORD = "mahachi2007"
    MAX_ERRORS = 10
    CHECK_INTERVAL = 5

LOGIN_URL = "https://www.orangecarrier.com/login"
CALL_URL = "https://www.orangecarrier.com/live/calls"
BASE_URL = "https://www.orangecarrier.com"

BANNER_URL = "https://files.catbox.moe/zybusj.jpg"

NUMBER_CHANNEL_URL = "https://t.me/mrafrixtech"
BACKUP_CHANNEL_URL = "https://t.me/auroratechinc"
CONTACT_DEV_URL = "https://t.me/jadenafrix"

REFRESH_PATTERN = [1800, 1545, 2110, 1850, 1340]
