"""Contain quickbooks setup backend logic."""
import os, time, httpx, base64, json, redis
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv

load_dotenv("../.env")

# Constant for client id.
CLIENT_ID = os.getenv("QUICKBOOKS_CLIENT_ID")
# Constant for client secret.
CLIENT_SECRET = os.getenv("QUICKBOOKS_CLIENT_SECRET")
# Constant for redirect URI.
REDIRECT_URI = "https://oswaldo-nesh-cristy.ngrok-free.dev/callback"
# Constant for redis URL.
REDIS_URL = "redis://localhost:6379"

_redis = redis.from_url(REDIS_URL, decode_responses=True)

# Constant for scopes.
SCOPES = "com.intuit.quickbooks.accounting"

def bootstrap_token(access_token, expires_in, refresh_token):
    """Execute bootstrap token."""
    data = {
        "access_token": access_token,
        "expires_at": time.time() + expires_in - 120,
        "refresh_token": refresh_token,
    }
    _redis.set("token:quickbooks", json.dumps(data))
    print("Token bootstrapped into Redis!")

class Handler(BaseHTTPRequestHandler):
    """Represent the Handler component and its related behavior."""
    def do_GET(self):
        """Execute do GET for Handler."""
        params = parse_qs(urlparse(self.path).query)
        code = params.get("code", [None])[0]
        realm_id = params.get("realmId", [None])[0]

        if not code:
            return

        creds = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        r = httpx.post(
            "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
            }
        )
        data = r.json()
        print("Token response:", data)

        if "access_token" not in data:
            print("Failed to get token:", data)
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Token exchange failed. Check terminal.")
            return

        print("REALM ID (company ID):", realm_id)
        bootstrap_token(data["access_token"], data["expires_in"], data["refresh_token"])

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Done! Check terminal.")

    def log_message(self, *args):  # type: ignore
        """Suppress default HTTP server request logging in setup flow."""
        pass

print("CLIENT_ID loaded:", CLIENT_ID)
print("\nVisit this URL in browser:")
print(f"https://appcenter.intuit.com/connect/oauth2?client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope={SCOPES}&state=123")
print("\nWaiting for callback on port 8001...")
HTTPServer(("localhost", 8001), Handler).serve_forever()