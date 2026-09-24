"""Status console contract checks for NEWAPP-006 ("Establish automated status console").

The console itself is ``start_agent.bat`` plus ``.ai/controller/agent_loop.py``; both are protected
control-plane paths and are read-only for this task. This package adds the allowed-path tests and the
read-only diagnostic that prove the console contract:

    python -m unittest discover -s tests/console -p "test_*.py"
    python tests/console/status_snapshot.py --write --report .ai/generated/NEWAPP-006-status-console.json
"""
