"""Login with Yandex ID and Google (OAuth 2.0 authorization-code flow), signed-cookie sessions, optional allowlist.

Configuration (environment):
  AUTH_YANDEX_CLIENT_ID / AUTH_YANDEX_CLIENT_SECRET     https://oauth.yandex.ru  (scope login:email login:info)
  AUTH_GOOGLE_CLIENT_ID / AUTH_GOOGLE_CLIENT_SECRET     https://console.cloud.google.com  (scopes openid email profile)
  AUTH_PUBLIC_URL     base URL users open, e.g. https://185-17-3-218.sslip.io  (callbacks: <url>/auth/<provider>/callback)
  AUTH_ALLOWED_EMAILS comma list of emails allowed in (optional)
  AUTH_ALLOWED_DOMAINS comma list of email domains allowed in, e.g. phystech.edu,mipt.ru (optional)
  SESSION_SECRET      random string for cookie signing (required when any provider is set)
Login is enforced as soon as one provider is configured (or AUTH_REQUIRED=1). Without providers the app stays open.
"""
import os, secrets, urllib.parse
import requests
from .common import log

PROVIDERS = {
    "yandex": {"name": "Яндекс ID", "authorize": "https://oauth.yandex.ru/authorize", "token": "https://oauth.yandex.ru/token",
               "scope": "login:email login:info"},
    "google": {"name": "Google", "authorize": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token",
               "scope": "openid email profile"},
}


def _cfg(p):
    return os.environ.get(f"AUTH_{p.upper()}_CLIENT_ID", "").strip(), os.environ.get(f"AUTH_{p.upper()}_CLIENT_SECRET", "").strip()


def enabled_providers():
    return [p for p in PROVIDERS if all(_cfg(p))]


def demo_enabled():
    return os.environ.get("AUTH_DEMO") == "1"


def required():
    return bool(enabled_providers()) or os.environ.get("AUTH_REQUIRED") == "1" or demo_enabled()


def demo_user(name=None):
    """Anonymous demo session: no personal data, a random id per visitor so feedback stays separable."""
    nm = (name or "").strip()[:60] or "Демо-пользователь"
    return {"id": "demo:" + secrets.token_hex(6), "email": None, "name": nm, "provider": "demo"}


def public_url(request):
    return os.environ.get("AUTH_PUBLIC_URL", "").rstrip("/") or str(request.base_url).rstrip("/")


def callback_url(request, p):
    return f"{public_url(request)}/auth/{p}/callback"


def authorize_redirect(request, p):
    cid, _ = _cfg(p)
    state = secrets.token_urlsafe(24); request.session["oauth_state"] = state; request.session["oauth_provider"] = p
    q = {"response_type": "code", "client_id": cid, "redirect_uri": callback_url(request, p), "state": state, "scope": PROVIDERS[p]["scope"]}
    if p == "google": q.update({"access_type": "online", "prompt": "select_account"})
    if p == "yandex": q.update({"force_confirm": "no"})
    return PROVIDERS[p]["authorize"] + "?" + urllib.parse.urlencode(q)


def finish(request, p, code, state):
    """Exchange the code, fetch the profile, apply the allowlist. Returns (user, error)."""
    if not state or state != request.session.pop("oauth_state", None) or request.session.pop("oauth_provider", None) != p:
        return None, "Сессия входа устарела, попробуйте ещё раз."
    cid, secret = _cfg(p)
    try:
        tok = requests.post(PROVIDERS[p]["token"], data={"grant_type": "authorization_code", "code": code, "client_id": cid, "client_secret": secret,
                                                        "redirect_uri": callback_url(request, p)}, timeout=20)
        tok.raise_for_status(); access = tok.json()["access_token"]
        if p == "yandex":
            info = requests.get("https://login.yandex.ru/info?format=json", headers={"Authorization": f"OAuth {access}"}, timeout=20).json()
            user = {"id": f"yandex:{info.get('id')}", "email": (info.get("default_email") or "").lower(),
                    "name": info.get("real_name") or info.get("display_name") or info.get("login"), "provider": "yandex"}
        else:
            info = requests.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {access}"}, timeout=20).json()
            if info.get("email_verified") is False: return None, "Адрес Google не подтверждён."
            user = {"id": f"google:{info.get('sub')}", "email": (info.get("email") or "").lower(), "name": info.get("name") or info.get("email"),
                    "provider": "google", "picture": info.get("picture")}
    except Exception as ex:  # noqa
        log.warning("oauth %s failed: %s", p, ex); return None, "Не удалось получить данные от провайдера входа."
    emails = {e.strip().lower() for e in os.environ.get("AUTH_ALLOWED_EMAILS", "").split(",") if e.strip()}
    domains = {d.strip().lower().lstrip("@") for d in os.environ.get("AUTH_ALLOWED_DOMAINS", "").split(",") if d.strip()}
    if (emails or domains) and not (user["email"] in emails or user["email"].split("@")[-1] in domains):
        return None, f"Адрес {user['email'] or '(без email)'} не имеет доступа к этой системе."
    log.info("login %s %s", user["provider"], user["email"])
    return user, None
