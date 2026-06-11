import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "sensor-service"))
os.chdir(os.path.join(os.path.dirname(__file__), "sensor-service"))
from app import socketio, app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, allow_unsafe_werkzeug=True)
