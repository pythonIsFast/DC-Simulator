"""Android entry point: starts the Flask app in a background thread (Chaquopy)."""
import os
import threading

_server = None


def start(res_dir, data_dir, port=5000):
    """Start the local server once and return after the socket is bound."""
    global _server
    if _server is not None:
        return
    # Must be set before config/db are imported.
    os.environ["DC_FRONTEND_DIR"] = os.path.join(res_dir, "frontend")
    os.environ["DC_SCHEMA_PATH"] = os.path.join(res_dir, "schema.sql")
    os.environ["DC_INSTANCE_DIR"] = data_dir

    from werkzeug.serving import make_server

    from app import create_app

    _server = make_server("127.0.0.1", port, create_app(), threaded=True)
    threading.Thread(target=_server.serve_forever, daemon=True).start()
