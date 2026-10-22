"""Envoi de l'etat de la LED bicolore a l'ESP8266 (WiFi, HTTP).

Etats : off, green_blink, green_solid, red_blink, red_solid.
Les durees (30 s fixe, 10 clignotements) sont gerees par l'ESP8266 lui-meme.
Si ESP_URL est vide, rien n'est envoye (mode sans carte) mais l'etat est memorise.
"""
import os
import threading

import requests

ESP_URL = os.getenv("ESP_URL", "").rstrip("/")  # ex. http://192.168.1.50
ESP_KEY = os.getenv("ESP_KEY", "")  # cle partagee avec le firmware
ETATS = {"off", "green_blink", "green_solid", "red_blink", "red_solid"}

dernier = {"etat": "off", "envoye": None}


def envoyer(etat):
    if etat not in ETATS:
        raise ValueError(f"etat LED inconnu : {etat}")
    dernier["etat"] = etat
    if not ESP_URL:
        dernier["envoye"] = None
        return

    def _go():
        try:
            r = requests.get(f"{ESP_URL}/led", params={"state": etat, "key": ESP_KEY}, timeout=2)
            dernier["envoye"] = r.ok
        except requests.RequestException:
            dernier["envoye"] = False

    threading.Thread(target=_go, daemon=True).start()
