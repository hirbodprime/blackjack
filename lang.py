# lang.py

LANG = {
    "welcome": {
        "en": "Welcome to the game!",
        "fa": "به بازی خوش آمدید!",
    },
    "settings": {
        "en": "Settings",
        "fa": "تنظیمات",
    },
    # Add more keys here...
}

def t(key, lang="en"):
    return LANG.get(key, {}).get(lang, LANG.get(key, {}).get("en", key))
