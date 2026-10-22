# Connexion back-office : visage (camera USB du PC hote) + LED ESP8266

## Fichiers
- ia/face/ : serveur (main.py, led.py, static/*.html)
- ia/requirements-face.txt, ia/Dockerfile.face
- esp8266-led/ : projet PlatformIO (ouvrir ce dossier dans CLion)

## Modeles a telecharger (dans ia/models/face/)
- face_detection_yunet_2023mar.onnx
- face_recognition_sface_2021dec.onnx
  (depuis https://github.com/opencv/opencv_zoo/tree/main/models)

## Lancer sur le PC hote (sans Docker, recommande sous Windows)
    cd ia
    pip install -r requirements-face.txt
    # PowerShell : $env:ADMIN_TOKEN="un-jeton-long" ; $env:ESP_URL="http://IP_ESP" ; $env:ESP_KEY="cle"
    # Linux : export ADMIN_TOKEN=... ESP_URL=... ESP_KEY=...
    uvicorn face.main:app --host 0.0.0.0 --port 8600
Connexion : http://localhost:8600/   Habilitations : http://localhost:8600/admin
(opencv-python-headless suffit : le serveur lit la camera, il n'ouvre aucune fenetre)

## Lancer avec Docker (PC hote Linux)
    docker build -f Dockerfile.face -t ra-face .
    docker run -d --name ra-face -p 8600:8600 --device /dev/video0 \
      -e ADMIN_TOKEN=... -e ESP_URL=http://IP_ESP -e ESP_KEY=... -v face-data:/app/data ra-face

## ESP8266
1. Copier include/secrets.h.example en include/secrets.h et le remplir (WiFi du point d'acces, cle).
2. Cabler : LED rouge -> D1, LED verte -> D2, resistances 220 ohms, cathode commune au GND.
3. Televerser (PlatformIO), ouvrir le moniteur serie, noter l'adresse IP -> ESP_URL.

## Regles implementees
- Identifiant -> camera -> visage OK -> mot de passe. Sinon identifiant vide, camera eteinte.
- 2 essais de visage, puis blocage 5 min (10, 20 min... aux blocages suivants).
- LED : repos eteinte ; visage OK vert clignotant ; mot de passe OK vert fixe 30 s ;
  mot de passe faux rouge x10 puis tout recommence ; visage refuse rouge fixe 30 s.

## Contrat d'API pour le front / le back-office (port 8600, HTTP)
Variables d'environnement : ADMIN_TOKEN (admin), SERVICE_KEY (mode integre), CORS_ORIGINS (origines du front, separees par des virgules), ESP_URL, ESP_KEY.
La camera est lue par LE SERVEUR (PC hote) : le front n'envoie AUCUNE image.

1) POST /auth/identify  {"user":"alice"}            (camera allumee ~8 s max, eteinte ensuite)
   -> 200 {"ok":true,"score":0.71,"token":"..."}     visage reconnu (LED verte clignotante)
   -> 200 {"ok":false,"score":0.12,"pause_s":30,"bloque_s":0,"message":"..."}   visage refuse (LED rouge fixe 30 s)
   -> 429 {"detail":"compte bloque...","retry_after":300}   bloque 5 min (puis 10, 20...)
   -> 409 {"detail":"poste occupe...","retry_after":N}      attendre la fin des 30 s de LED rouge
   -> 503 camera USB introuvable

2a) Mode autonome : POST /auth/password {"user":"alice","password":"...","token":"..."}
    -> 200 {"ok":true,"session":"...","role":"operateur","expire_dans_s":900}   (LED verte fixe 30 s)
    -> 403 {"ok":false,"recommencer":true}                                      (LED rouge x10, tout recommence)
    GET /auth/me  (Authorization: Bearer <session>) -> {"user","role"}

2b) Mode integre (le back-office verifie le mot de passe lui-meme) :
    POST /auth/confirm  header X-Service-Key: <SERVICE_KEY>  {"user":"alice","token":"...","ok":true|false}
    -> 200 {"ok":true,"recommencer":false|true}   (pilote la LED : vert fixe 30 s ou rouge x10)

Habilitations (header X-Admin-Token) : GET/POST /admin/users, POST /admin/users/{u}/face,
PATCH/DELETE /admin/users/{u}, POST /admin/users/{u}/unblock, GET /admin/journal.  Page : /admin
