from app.main import app

for path, methods in sorted(app.openapi()["paths"].items()):
    print(", ".join(m.upper() for m in methods), path)