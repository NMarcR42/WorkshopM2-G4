"""Un passage du parcours client : login -> virement -> vérification comptable, via le WAF.

C'est la seule vraie preuve de reprise : /health d'un conteneur peut être vert alors que
les paiements échouent. Ici, le service est sain si et seulement si un paiement complet passe.
"""
import time
import uuid

import httpx

from .config import secret, settings


class StepFailed(Exception):
    pass


def _expect(step: str, ok: bool, detail: str) -> None:
    if not ok:
        raise StepFailed(f"{step}: {detail}")


def run_probe() -> dict:
    """Joue UNE passe. Ne lève jamais : renvoie {ok, duration_s, failed_step, detail, steps}."""
    started = time.perf_counter()
    steps: list[dict] = []
    failed = None
    detail = "paiement et cohérence comptable OK"

    def step(name: str, call):
        t0 = time.perf_counter()
        try:
            call()
            steps.append({"step": name, "ok": True, "ms": round((time.perf_counter() - t0) * 1000)})
        except Exception:
            steps.append({"step": name, "ok": False, "ms": round((time.perf_counter() - t0) * 1000)})
            raise

    try:
        _expect("config", bool(settings.waf_url), "WAF_URL non défini")
        password = secret("CANARY_PASSWORD")
        _expect("config", bool(password), "mot de passe canary absent (CANARY_PASSWORD_FILE)")

        # Un client neuf par passe (pas de connexion réutilisée) : chaque passe repart de zéro, comme un nouveau client.
        with httpx.Client(base_url=settings.waf_url, timeout=settings.timeout_s) as http:
            ctx: dict = {}

            def login():
                r = http.post(f"{settings.auth_prefix}/login", json={"username": settings.username, "password": password})
                _expect("login", r.status_code == 200, f"HTTP {r.status_code}")
                ctx["headers"] = {"Authorization": f"Bearer {r.json()['access_token']}"}

            def pay():
                # Clé neuve à chaque passe (sinon l'API rejouerait l'ancienne transaction sans rien prouver) ;
                # elle protège d'un double débit si la requête est rejouée par un intermédiaire.
                body = {
                    "from_account": settings.from_account,
                    "to_account": settings.to_account,
                    "amount": settings.amount,
                    "currency": settings.currency,
                }
                r = http.post(
                    f"{settings.api_prefix}/v1/transactions",
                    json=body,
                    headers={**ctx["headers"], "Idempotency-Key": f"canary-{uuid.uuid4()}"},
                )
                _expect("transaction", r.status_code in (200, 201), f"HTTP {r.status_code}")
                _expect("transaction", r.json().get("status") == "COMPLETED", f"statut {r.json().get('status')}")

            def ledger():
                r = http.get(f"{settings.api_prefix}/v1/ledger/check", headers=ctx["headers"])
                _expect("ledger", r.status_code == 200, f"HTTP {r.status_code}")
                check = r.json()
                _expect("ledger", check.get("consistent") is True, f"comptes incohérents: {check.get('mismatches')}")

            step("login", login)
            step("transaction", pay)
            step("ledger", ledger)
    except StepFailed as exc:
        failed, detail = str(exc).split(":", 1)[0], str(exc)
    except httpx.TimeoutException:
        failed = _next_step(steps)
        detail = f"{failed}: délai dépassé ({settings.timeout_s}s)"
    except httpx.HTTPError as exc:
        failed = _next_step(steps)
        detail = f"{failed}: service injoignable ({type(exc).__name__})"
    except Exception as exc:  # réponse mal formée, etc. : un échec de sonde, jamais un crash du canary
        failed = _next_step(steps)
        detail = f"{failed}: réponse inattendue ({type(exc).__name__})"

    return {
        "ok": failed is None,
        "duration_s": round(time.perf_counter() - started, 3),
        "failed_step": failed,
        "detail": detail,
        "steps": steps,
    }


def _next_step(steps: list[dict]) -> str:
    """Étape en cours au moment de l'exception (celle qui a échoué, enregistrée ou non)."""
    for s in steps:
        if not s["ok"]:
            return s["step"]
    return ("login", "transaction", "ledger")[min(len(steps), 2)]
