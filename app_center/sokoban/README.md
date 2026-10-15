# 推箱子

Dedicated, client-side Sokoban application. The platform catalog provides discovery
and launch; no executor, AI call, game API or game database is needed.

The React renderer contains 20 original fixed maps. Each map has a legal solution
in the test fixtures, verified by replay. SVG artwork is authored in this project.
Browser storage is scoped by organization, user, application and schema version.
It preserves each level's move history and best score; it does not sync devices.

From the repository root on Windows:

```powershell
backend\venv\Scripts\python.exe backend\manage.py validate_app_center
backend\venv\Scripts\python.exe backend\manage.py sync_app_center --package sokoban
```

No migrations or extra dependencies are required. Other environments use their
project virtual environment for the same management commands.
