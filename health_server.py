"""
Einfacher Health-Check Server für Render
Läuft parallel zum Bot und antwortet auf /health
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import threading
import time

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            
            health_data = {
                'status': 'healthy',
                'timestamp': time.time(),
                'service': 'mib-bot',
                'uptime': time.time() - start_time
            }
            
            self.wfile.write(json.dumps(health_data).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Unterdrücke HTTP-Logs
        pass

start_time = time.time()

def start_health_server():
    """Startet den Health-Check Server auf Port 8000 (Koyeb Standard)"""
    port = int(os.environ.get('PORT', 8000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"🏥 Health-Server läuft auf Port {port}")
    server.serve_forever()

if __name__ == "__main__":
    import os
    start_health_server()