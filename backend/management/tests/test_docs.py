import pytest

from app.main import DOCS_ASSETS_DIR, app, swagger_ui_html


@pytest.mark.asyncio
async def test_swagger_docs_use_local_assets():
    response = await swagger_ui_html()
    html = response.body.decode("utf-8")

    assert app.docs_url is None
    assert app.redoc_url is None
    assert "/docs-assets/swagger-ui-bundle.js" in html
    assert "/docs-assets/swagger-ui.css" in html
    assert "/docs-assets/swagger-init.js" in html
    assert "cdn.jsdelivr.net" not in html
    assert "SwaggerUIBundle({" not in html
    assert (DOCS_ASSETS_DIR / "swagger-ui-bundle.js").is_file()
    assert (DOCS_ASSETS_DIR / "swagger-ui.css").is_file()
    assert (DOCS_ASSETS_DIR / "swagger-init.js").is_file()
