from __future__ import annotations

from flask import Flask, jsonify, request
from pymysql import MySQLError

from .config import settings
from .errors import NotFoundError, ServiceError, UpstreamError, ValidationError
from .routes.customers import customers_bp
from .routes.dashboard import dashboard_bp


def create_app(*, testing: bool = False) -> Flask:
    app = Flask(__name__)
    app.config.update(TESTING=testing, JSON_AS_ASCII=False)
    app.register_blueprint(customers_bp)
    app.register_blueprint(dashboard_bp)

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "customer-profile"})

    @app.after_request
    def add_cors_headers(response):
        origin = request.headers.get("Origin")
        if origin in settings.cors_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Content-Type"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        return response

    @app.errorhandler(ValidationError)
    def handle_validation_error(exc):
        return jsonify({"code": 400, "message": str(exc), "data": None}), 400

    @app.errorhandler(NotFoundError)
    def handle_not_found(exc):
        return jsonify({"code": 404, "message": str(exc), "data": None}), 404

    @app.errorhandler(UpstreamError)
    def handle_upstream_error(exc):
        app.logger.exception("Upstream service error")
        return jsonify({"code": 502, "message": str(exc), "data": None}), 502

    @app.errorhandler(ServiceError)
    def handle_service_error(exc):
        app.logger.exception("Service error")
        return jsonify({"code": 503, "message": str(exc), "data": None}), 503

    @app.errorhandler(MySQLError)
    def handle_mysql_error(exc):
        app.logger.exception("Database error")
        return jsonify({"code": 503, "message": "database unavailable", "data": None}), 503

    return app
