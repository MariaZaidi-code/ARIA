import ast
try:
    with open("api/schema_routes.py") as f:
        ast.parse(f.read())
    print("Syntax OK")
except SyntaxError as e:
    print(f"Syntax error: {e}")
