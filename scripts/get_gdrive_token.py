"""
One-time helper: get the GOOGLE_REFRESH_TOKEN that lets the web app upload backups to YOUR Google Drive.

Run it on your own PC (it opens a browser window):

    python scripts/get_gdrive_token.py <CLIENT_ID> <CLIENT_SECRET>

Create the CLIENT_ID / CLIENT_SECRET first in Google Cloud Console (type "Desktop app") — see README, section
"Google Drive backup". The script prints the three values to paste into Render -> Environment.
Only the Python standard library is needed.
"""
import http.server
import json
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser

SCOPE = "https://www.googleapis.com/auth/drive.file"   # only files/folders this app creates


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    client_id, client_secret = sys.argv[1].strip().strip("\"'"), sys.argv[2].strip().strip("\"'")
    # catch the usual copy/paste mistakes BEFORE sending anything to Google
    if client_id.startswith("GOCSPX-") and client_secret.endswith(".apps.googleusercontent.com"):
        client_id, client_secret = client_secret, client_id
        print("Note: the two values were in the wrong order - I swapped them for you.")
    problems = []
    if not client_id.endswith(".apps.googleusercontent.com") or " " in client_id:
        problems.append("The Client ID must be the FULL value ending in .apps.googleusercontent.com "
                        "(example: 123456789012-abc123xyz.apps.googleusercontent.com), with no spaces.")
    if not client_secret or " " in client_secret or client_secret.endswith(".apps.googleusercontent.com"):
        problems.append("The Client secret is the second value (usually starts with GOCSPX-), with no spaces.")
    if problems:
        sys.exit("\nCannot continue:\n - " + "\n - ".join(problems) +
                 '\n\nUsage:  python scripts/get_gdrive_token.py "CLIENT_ID" "CLIENT_SECRET"')
    print(f"Using Client ID: {client_id[:12]}...{client_id[-30:]}")
    got = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got["code"] = (q.get("code") or [""])[0]
            got["error"] = (q.get("error") or [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>✅ Done — you can close this tab and go back to the terminal.</h2>".encode("utf-8"))
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{server.server_port}"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent"})
    print("\nOpening your browser. Sign in with the Google account whose Drive should store the backups.")
    try:
        with open("gdrive_sign_in_link.txt", "w", encoding="utf-8") as fh:
            fh.write(url)
        print("If the browser does not open, open the file gdrive_sign_in_link.txt (next to where you ran this),")
        print("copy the whole line from it, and paste it into your browser. Do NOT copy it from this window - long lines get cut.\n")
    except OSError:
        print("If it does not open, copy this link into the browser:\n\n" + url + "\n")
    webbrowser.open(url)
    server.serve_forever()

    if not got.get("code"):
        sys.exit(f"No authorisation code received ({got.get('error') or 'cancelled'}).")
    data = urllib.parse.urlencode({"code": got["code"], "client_id": client_id, "client_secret": client_secret,
                                   "redirect_uri": redirect, "grant_type": "authorization_code"}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=30) as r:
            tok = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit("Google refused the code: " + e.read().decode("utf-8", "replace"))
    if not tok.get("refresh_token"):
        sys.exit("Google did not return a refresh token. Remove the app at https://myaccount.google.com/permissions and run again.")
    print("\n✅ Success! Add these three Environment variables in Render (and keep them secret):\n")
    print(f"GOOGLE_CLIENT_ID={client_id}")
    print(f"GOOGLE_CLIENT_SECRET={client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={tok['refresh_token']}\n")


if __name__ == "__main__":
    main()
