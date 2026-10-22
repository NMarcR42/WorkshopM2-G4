// LED bicolore rouge/vert pilotee en WiFi (ESP8266, NodeMCU).
// Cablage : LED rouge sur D1 (GPIO5), LED verte sur D2 (GPIO4), chacune avec une
// resistance de 220 ohms en serie, l'autre patte au GND (cathode commune).
// Requete : GET /led?state=off|green_blink|green_solid|red_blink|red_solid&key=CLE
#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include "secrets.h"

const uint8_t PIN_ROUGE = D1;
const uint8_t PIN_VERT = D2;
const unsigned long DUREE_FIXE_MS = 30000;   // vert fixe / rouge fixe : 30 s
const unsigned long PERIODE_CLIGNO_MS = 500; // clignotement
const int NB_CLIGNOTEMENTS_ROUGE = 10;

enum Etat { OFF, VERT_CLIGNO, VERT_FIXE, ROUGE_CLIGNO, ROUGE_FIXE };
Etat etat = OFF;
unsigned long debut = 0;

ESP8266WebServer serveur(80);

void ecrire(bool rouge, bool vert) {
  digitalWrite(PIN_ROUGE, rouge ? HIGH : LOW);
  digitalWrite(PIN_VERT, vert ? HIGH : LOW);
}

void changer(Etat e) {
  etat = e;
  debut = millis();
}

void gererLed() {
  unsigned long ecoule = millis() - debut;
  bool allume = (ecoule / PERIODE_CLIGNO_MS) % 2 == 0;  // 500 ms allume, 500 ms eteint
  switch (etat) {
    case OFF:
      ecrire(false, false);
      break;
    case VERT_CLIGNO:  // jusqu'a la saisie du mot de passe (nouvel ordre du serveur)
      ecrire(false, allume);
      break;
    case VERT_FIXE:
      ecrire(false, true);
      if (ecoule >= DUREE_FIXE_MS) changer(OFF);
      break;
    case ROUGE_CLIGNO:  // 10 clignotements puis eteinte
      ecrire(allume, false);
      if (ecoule >= (unsigned long)NB_CLIGNOTEMENTS_ROUGE * 2 * PERIODE_CLIGNO_MS) changer(OFF);
      break;
    case ROUGE_FIXE:
      ecrire(true, false);
      if (ecoule >= DUREE_FIXE_MS) changer(OFF);
      break;
  }
}

void routeLed() {
  if (serveur.arg("key") != API_KEY) {
    serveur.send(403, "text/plain", "cle invalide");
    return;
  }
  String s = serveur.arg("state");
  if (s == "off") changer(OFF);
  else if (s == "green_blink") changer(VERT_CLIGNO);
  else if (s == "green_solid") changer(VERT_FIXE);
  else if (s == "red_blink") changer(ROUGE_CLIGNO);
  else if (s == "red_solid") changer(ROUGE_FIXE);
  else {
    serveur.send(400, "text/plain", "etat inconnu");
    return;
  }
  serveur.send(200, "text/plain", "ok " + s);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_ROUGE, OUTPUT);
  pinMode(PIN_VERT, OUTPUT);
  ecrire(false, false);  // par defaut : LED eteinte

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connexion WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Adresse IP : ");
  Serial.println(WiFi.localIP());  // a noter : c'est ESP_URL cote serveur

  serveur.on("/led", routeLed);
  serveur.on("/health", []() { serveur.send(200, "text/plain", "ok"); });
  serveur.begin();
}

void loop() {
  serveur.handleClient();
  gererLed();
  if (WiFi.status() != WL_CONNECTED) {  // reconnexion automatique
    WiFi.reconnect();
    delay(500);
  }
}
