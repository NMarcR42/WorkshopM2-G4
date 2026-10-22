"""Authentification back-office : identifiant -> visage (camera USB du PC hote) -> mot de passe.

- La camera est lue par LE SERVEUR (PC hote), jamais par le navigateur.
- On ne garde que des empreintes numeriques de visages (jamais de photos).
- Blocage : 2 essais de visage, puis 5 min, puis 10, 20... (double a chaque blocage).
- La LED de l'ESP8266 suit chaque etape (voir led.py).
- Habilitations (ajout / modification / suppression des utilisateurs) : routes /admin/*.
"""
import hashlib
import hmac
import json
import math
import os
import secrets
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import led

DATA = Path(os.getenv("FACE_DATA", "data/face"))
DET_MODEL = os.getenv("FACE_DET_MODEL", "models/face/face_detection_yunet_2023mar.onnx")
REC_MODEL = os.getenv("FACE_REC_MODEL", "models/face/face_recognition_sface_2021dec.onnx")
CAM_INDEX = int(os.getenv("CAM_INDEX", "1"))
CAM_BACKEND = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
CAM_CHAUFFE = 10  # images jetees a l'ouverture (les premieres sont souvent noires)
SEUIL = float(os.getenv("FACE_SEUIL", "0.363"))  # similarite cosinus recommandee pour SFace
CAPTURE_TIMEOUT_S = float(os.getenv("CAPTURE_TIMEOUT_S", "8"))
MAX_ESSAIS = int(os.getenv("MAX_ESSAIS", "2"))  # 1 essai + 1 nouvel essai
BLOCAGE_BASE_S = int(os.getenv("BLOCAGE_BASE_S", "300"))  # 5 minutes
PAUSE_ECHEC_S = int(os.getenv("PAUSE_ECHEC_S", "30"))  # LED rouge fixe 30 s
TOKEN_TTL_S = int(os.getenv("TOKEN_TTL_S", "120"))  # temps pour saisir le mot de passe
SESSION_TTL_S = int(os.getenv("SESSION_TTL_S", "900"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
SERVICE_KEY = os.getenv("SERVICE_KEY", "")  # cle du back-office pour /auth/confirm
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")  # jamais dans le code : variable d'environnement

DATA.mkdir(parents=True, exist_ok=True)
FICHIER = DATA / "users.json"
JOURNAL = DATA / "journal.jsonl"

_verrou = threading.Lock()
_moteur = {}
_etapes = {}      # user -> {"token", "exp"}   visage valide, mot de passe attendu
_sessions = {}    # token -> {"user", "role", "exp"}
_blocages = {}    # user -> {"echecs", "niveau", "jusqua"}
_poste = {"pause_jusqua": 0.0}  # un seul poste physique (une camera, une LED)


# ---------- Utilitaires ----------
def norm(user):
    return user.strip().lower()


def journaliser(evenement, user="", detail=""):
    ligne = {"t": int(time.time()), "evenement": evenement, "user": user, "detail": detail}
    with open(JOURNAL, "a", encoding="utf-8") as f:
        f.write(json.dumps(ligne, ensure_ascii=False) + "\n")


def refus(code, message, retry_after=None):
    corps = {"detail": message}
    entetes = {}
    if retry_after is not None:
        corps["retry_after"] = int(retry_after)
        entetes["Retry-After"] = str(int(retry_after))
    return JSONResponse(corps, status_code=code, headers=entetes)


def lire_users():
    return json.loads(FICHIER.read_text()) if FICHIER.exists() else {}


def ecrire_users(users):
    FICHIER.write_text(json.dumps(users))


def hacher(mot_de_passe, sel):
    return hashlib.scrypt(mot_de_passe.encode(), salt=sel, n=2**14, r=8, p=1, dklen=32)


def mdp_ok(user_rec, mot_de_passe):
    attendu = user_rec["hash"]
    calcule = hacher(mot_de_passe, bytes.fromhex(user_rec["sel"])).hex()
    return hmac.compare_digest(calcule, attendu)


def exiger_admin(x_admin_token):
    if not ADMIN_TOKEN:
        raise HTTPException(503, "administration desactivee (ADMIN_TOKEN non defini)")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(403, "acces administrateur refuse")


# ---------- Camera USB (PC hote) ----------
_cam = {"cap": None, "timer": None}
_cam_verrou = threading.RLock()


def camera_ouvrir():
    with _cam_verrou:
        if _cam["timer"]:
            _cam["timer"].cancel()
            _cam["timer"] = None
        if _cam["cap"] is None:
            cap = cv2.VideoCapture(CAM_INDEX, CAM_BACKEND)
            if not cap.isOpened():
                cap.release()
                raise HTTPException(503, "camera USB introuvable sur le PC hote")
            for _ in range(CAM_CHAUFFE):
                cap.read()
            _cam["cap"] = cap
        return _cam["cap"]


def camera_fermer():
    with _cam_verrou:
        if _cam["timer"]:
            _cam["timer"].cancel()
            _cam["timer"] = None
        if _cam["cap"] is not None:
            _cam["cap"].release()
            _cam["cap"] = None


def camera_fermer_dans(secondes):
    with _cam_verrou:
        if _cam["timer"]:
            _cam["timer"].cancel()
        t = threading.Timer(secondes, camera_fermer)
        t.daemon = True
        _cam["timer"] = t
        t.start()


def images_camera(duree_s):
    cap = camera_ouvrir()
    fin = time.time() + duree_s
    while time.time() < fin:
        ok, img = cap.read()
        if ok:
            yield img
        else:
            time.sleep(0.05)


# ---------- IA de visage (OpenCV YuNet + SFace) ----------
def charger_moteur():
    if not _moteur:
        _moteur["det"] = cv2.FaceDetectorYN.create(DET_MODEL, "", (320, 320), 0.8, 0.3, 5000)
        _moteur["rec"] = cv2.FaceRecognizerSF.create(REC_MODEL, "")
    return _moteur["det"], _moteur["rec"]


def empreinte_image(img):
    """Image -> vecteur de 128 nombres, ou None s'il n'y a pas exactement un visage."""
    det, rec = charger_moteur()
    det.setInputSize((img.shape[1], img.shape[0]))
    _, visages = det.detect(img)
    if visages is None or len(visages) != 1:
        return None
    return rec.feature(rec.alignCrop(img, visages[0])).flatten().astype(np.float32)


def similarite(a, b):
    a, b = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def reconnaitre(empreintes):
    """Regarde la camera jusqu'a CAPTURE_TIMEOUT_S. Renvoie (reconnu, meilleur_score)."""
    meilleur = 0.0
    for img in images_camera(CAPTURE_TIMEOUT_S):
        v = empreinte_image(img)
        if v is None:
            continue
        if empreintes:
            meilleur = max(meilleur, max(similarite(v, e) for e in empreintes))
        if meilleur >= SEUIL:
            return True, meilleur
    return False, meilleur


def capturer_empreintes(nombre=3):
    """Pour l'inscription : nombre d'empreintes prises a quelques instants d'ecart."""
    vecteurs, dernier = [], 0.0
    for img in images_camera(CAPTURE_TIMEOUT_S + 6):
        if time.time() - dernier < 0.7:
            continue
        v = empreinte_image(img)
        if v is not None:
            vecteurs.append(v.tolist())
            dernier = time.time()
            if len(vecteurs) >= nombre:
                break
    return vecteurs


# ---------- Blocage ----------
def blocage_restant(user):
    b = _blocages.get(user)
    return max(0, math.ceil(b["jusqua"] - time.time())) if b else 0


def noter_echec_visage(user):
    b = _blocages.setdefault(user, {"echecs": 0, "niveau": 0, "jusqua": 0.0})
    b["echecs"] += 1
    if b["echecs"] >= MAX_ESSAIS:
        b["jusqua"] = time.time() + BLOCAGE_BASE_S * (2 ** b["niveau"])
        b["niveau"] += 1
        b["echecs"] = 0
        journaliser("blocage", user, f"{int(b['jusqua'] - time.time())}s")


def effacer_echecs(user):
    _blocages.pop(user, None)


# ---------- API ----------
class Identification(BaseModel):
    user: str


class MotDePasse(BaseModel):
    user: str
    password: str
    token: str


class NouvelUtilisateur(BaseModel):
    user: str
    password: str
    role: str = "operateur"


class Modification(BaseModel):
    actif: bool | None = None
    role: str | None = None
    password: str | None = None


class Confirmation(BaseModel):
    user: str
    token: str
    ok: bool  # resultat de la verification du mot de passe par le back-office


app = FastAPI(title="Authentification back-office (visage + LED)")
if CORS_ORIGINS:  # ex. CORS_ORIGINS=http://192.168.1.10:3000,http://localhost:3000
    app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "ok", "seuil_visage": SEUIL, "led": led.dernier, "camera_index": CAM_INDEX}


@app.get("/")
def page_connexion():
    return FileResponse(Path(__file__).parent / "static" / "login.html")


@app.get("/backoffice")
def page_backoffice():
    # Page de demonstration : en vrai, c'est le back-office du dev qui prend le relais
    return FileResponse(Path(__file__).parent / "static" / "backoffice.html")


@app.get("/admin")
def page_admin():
    return FileResponse(Path(__file__).parent / "static" / "admin.html")


@app.post("/auth/identify")
def identify(req: Identification):
    user = norm(req.user)
    if not user:
        raise HTTPException(400, "identifiant requis")
    reste = blocage_restant(user)
    if reste:
        return refus(429, f"compte bloque, reessayez dans {reste} s", reste)
    pause = _poste["pause_jusqua"] - time.time()
    if pause > 0:
        return refus(409, f"poste occupe, patientez {int(pause) + 1} s", int(pause) + 1)

    if not _verrou.acquire(blocking=False):
        return refus(409, "une identification est deja en cours", 5)
    try:
        users = lire_users()
        rec = users.get(user)
        empreintes = rec["empreintes"] if rec and rec.get("actif", True) else []
        try:
            reconnu, score = reconnaitre(empreintes)
        except HTTPException:
            camera_fermer()
            led.envoyer("off")
            raise

        if reconnu:
            camera_fermer()  # la camera s'eteint
            effacer_echecs(user)
            token = secrets.token_hex(16)
            _etapes[user] = {"token": token, "exp": time.time() + TOKEN_TTL_S}
            led.envoyer("green_blink")  # vert clignotant jusqu'au mot de passe
            threading.Timer(TOKEN_TTL_S, _abandon, args=(user, token)).start()
            journaliser("visage_ok", user, f"score={score:.3f}")
            return {"ok": True, "score": round(score, 3), "token": token}

        # Visage non reconnu : LED rouge fixe 30 s, camera eteinte ensuite
        led.envoyer("red_solid")
        camera_fermer_dans(PAUSE_ECHEC_S)
        _poste["pause_jusqua"] = time.time() + PAUSE_ECHEC_S
        noter_echec_visage(user)
        journaliser("visage_refuse", user, f"score={score:.3f}")
        reste = blocage_restant(user)
        return {
            "ok": False,
            "score": round(score, 3),
            "pause_s": PAUSE_ECHEC_S,
            "bloque_s": reste,
            "message": "visage non reconnu" + (f", compte bloque {reste} s" if reste else ""),
        }
    finally:
        _verrou.release()


def _abandon(user, token):
    e = _etapes.get(user)
    if e and e["token"] == token:
        del _etapes[user]
        led.envoyer("off")
        journaliser("abandon", user)


@app.post("/auth/password")
def password(req: MotDePasse):
    user = norm(req.user)
    e = _etapes.pop(user, None)  # usage unique
    if not e or not hmac.compare_digest(e["token"], req.token) or e["exp"] < time.time():
        raise HTTPException(403, "verification du visage absente ou expiree")
    rec = lire_users().get(user)
    if not rec or not rec.get("actif", True) or not mdp_ok(rec, req.password):
        led.envoyer("red_blink")  # 10 clignotements rouges puis eteinte (ESP8266)
        journaliser("mdp_refuse", user)
        return JSONResponse({"ok": False, "recommencer": True, "detail": "mot de passe incorrect"}, status_code=403)
    led.envoyer("green_solid")  # vert fixe 30 s puis eteinte (ESP8266)
    session = secrets.token_hex(24)
    _sessions[session] = {"user": user, "role": rec.get("role", "operateur"), "exp": time.time() + SESSION_TTL_S}
    journaliser("connexion", user)
    return {"ok": True, "session": session, "role": rec.get("role", "operateur"), "expire_dans_s": SESSION_TTL_S}


@app.post("/auth/confirm")
def confirm(req: Confirmation, x_service_key: str = Header(default="")):
    """Mode integre : le back-office verifie LUI-MEME le mot de passe et nous donne le resultat
    (pour piloter la LED). Appel serveur a serveur, protege par SERVICE_KEY."""
    if not SERVICE_KEY:
        raise HTTPException(503, "mode integre desactive (SERVICE_KEY non defini)")
    if not hmac.compare_digest(x_service_key, SERVICE_KEY):
        raise HTTPException(403, "cle de service invalide")
    user = norm(req.user)
    e = _etapes.pop(user, None)  # usage unique
    if not e or not hmac.compare_digest(e["token"], req.token) or e["exp"] < time.time():
        raise HTTPException(403, "verification du visage absente ou expiree")
    if req.ok:
        led.envoyer("green_solid")
        journaliser("connexion", user, "confirme par le back-office")
    else:
        led.envoyer("red_blink")
        journaliser("mdp_refuse", user, "confirme par le back-office")
    return {"ok": True, "recommencer": not req.ok}


@app.get("/auth/me")
def me(authorization: str = Header(default="")):
    s = _sessions.get(authorization.removeprefix("Bearer ").strip())
    if not s or s["exp"] < time.time():
        raise HTTPException(401, "session absente ou expiree")
    return {"user": s["user"], "role": s["role"]}


# ---------- Habilitations (back-office) ----------
@app.get("/admin/users")
def admin_liste(x_admin_token: str = Header(default="")):
    exiger_admin(x_admin_token)
    return [
        {"user": u, "role": r.get("role", "operateur"), "actif": r.get("actif", True),
         "visages": len(r["empreintes"]), "bloque_s": blocage_restant(u)}
        for u, r in lire_users().items()
    ]


@app.post("/admin/users")
def admin_creer(req: NouvelUtilisateur, x_admin_token: str = Header(default="")):
    exiger_admin(x_admin_token)
    user = norm(req.user)
    users = lire_users()
    if not user or user in users:
        raise HTTPException(400, "identifiant vide ou deja existant")
    if len(req.password) < 8:
        raise HTTPException(400, "mot de passe de 8 caracteres minimum")
    sel = secrets.token_bytes(16)
    users[user] = {"sel": sel.hex(), "hash": hacher(req.password, sel).hex(),
                   "role": req.role, "actif": True, "empreintes": []}
    ecrire_users(users)
    journaliser("admin_creer", user, req.role)
    return {"ok": True}


@app.post("/admin/users/{user}/face")
def admin_visage(user: str, x_admin_token: str = Header(default="")):
    """Enregistre le visage de l'utilisateur devant la camera USB du PC hote."""
    exiger_admin(x_admin_token)
    user = norm(user)
    users = lire_users()
    if user not in users:
        raise HTTPException(404, "utilisateur inconnu")
    with _verrou:
        try:
            vecteurs = capturer_empreintes(3)
        finally:
            camera_fermer()
    if len(vecteurs) < 3:
        raise HTTPException(422, "visage non capture : un seul visage, bien eclaire, face a la camera")
    users[user]["empreintes"] = vecteurs  # remplace les anciennes empreintes
    ecrire_users(users)
    journaliser("admin_visage", user)
    return {"ok": True, "empreintes": len(vecteurs)}


@app.patch("/admin/users/{user}")
def admin_modifier(user: str, req: Modification, x_admin_token: str = Header(default="")):
    exiger_admin(x_admin_token)
    user = norm(user)
    users = lire_users()
    if user not in users:
        raise HTTPException(404, "utilisateur inconnu")
    if req.actif is not None:
        users[user]["actif"] = req.actif
    if req.role is not None:
        users[user]["role"] = req.role
    if req.password is not None:
        if len(req.password) < 8:
            raise HTTPException(400, "mot de passe de 8 caracteres minimum")
        sel = secrets.token_bytes(16)
        users[user]["sel"], users[user]["hash"] = sel.hex(), hacher(req.password, sel).hex()
    ecrire_users(users)
    journaliser("admin_modifier", user)
    return {"ok": True}


@app.delete("/admin/users/{user}")
def admin_supprimer(user: str, x_admin_token: str = Header(default="")):
    exiger_admin(x_admin_token)
    user = norm(user)
    users = lire_users()
    if user not in users:
        raise HTTPException(404, "utilisateur inconnu")
    del users[user]
    ecrire_users(users)
    effacer_echecs(user)
    journaliser("admin_supprimer", user)
    return {"ok": True}


@app.post("/admin/users/{user}/unblock")
def admin_debloquer(user: str, x_admin_token: str = Header(default="")):
    exiger_admin(x_admin_token)
    effacer_echecs(norm(user))
    journaliser("admin_debloquer", norm(user))
    return {"ok": True}


@app.get("/admin/journal")
def admin_journal(x_admin_token: str = Header(default="")):
    exiger_admin(x_admin_token)
    if not JOURNAL.exists():
        return []
    lignes = JOURNAL.read_text(encoding="utf-8").splitlines()[-100:]
    return [json.loads(x) for x in lignes]
