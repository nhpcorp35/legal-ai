from flask import Flask

app = Flask(__name__)

# --- ROOT TEST ---
@app.route("/")
def index():
    return "OK"

# --- HEALTH CHECK ---
@app.route("/healthz")
def healthz():
    return "healthy"


# --- IMPORTANT FOR RAILWAY ---
# Railway uses PORT env var
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)