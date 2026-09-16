from app.main import app


def test_docs_are_available_without_authentication():
    routes = {route.path: route for route in app.routes if hasattr(route, "path")}

    assert routes["/docs"].dependant.dependencies == []
    assert routes["/openapi.json"].dependant.dependencies == []


def test_authentication_endpoints_are_removed():
    route_paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert "/api/v1/auth/status" not in route_paths
    assert "/api/v1/auth/session" not in route_paths
