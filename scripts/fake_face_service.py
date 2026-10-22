"""IA simulée pour tester auth sans caméra : imite uniquement POST /auth/confirm du serveur de reconnaissance faciale.

Pourquoi un faux : le vrai serveur lit la caméra USB du PC hôte. Ici on vérifie seulement que `auth` applique
bien le contrat (clé de service, token à usage unique lié à l'utilisateur). Token accepté : "tok-<utilisateur>".
Usage : python scripts/fake_face_service.py <port> <fichier_cle_de_service>
"""
import hmac
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1])
KEY = open(sys.argv[2], encoding="utf-8").read().strip()
used = set()  # usage unique, comme le vrai service


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/auth/confirm":
            return self._send(404, {"detail": "inconnu"})
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if not hmac.compare_digest(self.headers.get("X-Service-Key", ""), KEY):
            return self._send(403, {"detail": "cle de service invalide"})
        token, user = req.get("token", ""), req.get("user", "")
        if token != f"tok-{user}" or token in used:
            return self._send(403, {"detail": "verification du visage absente ou expiree"})
        used.add(token)
        self._send(200, {"ok": True, "recommencer": not req.get("ok")})

    def log_message(self, *args):  # silence
        pass


HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
