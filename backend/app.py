"""Datacenter Tycoon backend entry point.

Run (from the backend directory):  python app.py
Initialize the database only:       python app.py --init-db
"""
import sys

from flask import Flask, jsonify, send_from_directory

import clock
import sim
from config import Config, FRONTEND_DIR
from db import init_db


def create_app(overrides=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    init_db(app)
    if sim.tick_world not in clock.TICK_HANDLERS:
        clock.TICK_HANDLERS.append(sim.tick_world)

    from routes import auth_routes, world_routes

    app.register_blueprint(auth_routes.bp)
    app.register_blueprint(world_routes.bp)

    @app.get("/api/health")
    def health():
        return jsonify(status="ok")

    @app.errorhandler(404)
    def not_found(_e):
        return jsonify(error="Not found"), 404

    # Serve the vanilla frontend (no build step).
    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/<path:path>")
    def static_files(path):
        return send_from_directory(FRONTEND_DIR, path)

    return app


if __name__ == "__main__":
    application = create_app()
    if "--init-db" in sys.argv:
        print("Database ready at", application.config["DATABASE"])
    else:
        application.run(host="127.0.0.1", port=5000, debug=False)
