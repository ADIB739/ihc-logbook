"""
IHC Logbook — Production Server
Run via start.bat (double-click) or: python start_server.py
"""
import socket
import os
from waitress import serve
from run import app

PORT = 5000

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    ip = get_local_ip()
    print("=" * 55)
    print("  IHC Digital Logbook — Production Server")
    print("=" * 55)
    print(f"  Local access  : http://localhost:{PORT}")
    print(f"  Network access: http://{ip}:{PORT}")
    print()
    print("  Share this URL with workers:")
    print(f"  >>> http://{ip}:{PORT} <<<")
    print()
    print("  Press Ctrl+C to stop the server.")
    print("=" * 55)
    serve(app, host="0.0.0.0", port=PORT, threads=8,
          channel_timeout=120, cleanup_interval=30)
