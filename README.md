# Punku — una mesa de partes

Punku («puerta» en quechua) es una mesa de partes: el registro de los documentos recibidos (ficha, remitente, plazo en
días hábiles) y una mesa de partes virtual pública donde cualquiera presenta un documento, recibe su cargo en PDF y
sigue su trámite. Es un módulo de [Tiqsi](https://github.com/achalmed/tiqsi): funciona solo, con el anfitrión mínimo
de Tiqsi, o dentro de una plataforma que lo monte por su manifiesto (como Qillqa).

**Recorrido interactivo:** <https://achalmed.github.io/punku/> (el código del sitio está en [`sitio/`](sitio/)).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -e '.[pruebas,sola]'   # requiere tiqsi
.venv/bin/python -m pytest -q tests
npm install && npm run web:construir && npm run web:pruebas
PUNKU_DATABASE_URL=postgresql+asyncpg://…/punku JWT_SECRET=<32 o más caracteres> PUNKU_WEB=web/dist \
  .venv/bin/uvicorn punku.sola:app --port 8034
```

Esta es una **versión de demostración**. Licencia: AGPL-3.0 (`LICENSE`).
