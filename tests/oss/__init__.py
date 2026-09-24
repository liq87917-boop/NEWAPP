"""Shared OSS contract checks for NEWAPP-004 ("Inspect shared OSS contract").

Regenerate the value-free artifacts of this task from the repository root:

    python -m unittest discover -s tests/oss -p "test_*.py"
    python tests/oss/oss_contract.py --write --report .ai/generated/NEWAPP-004-oss-contract.json --markdown docs/SHARED_OSS_CONTRACT.md --executor-file tests/oss/__init__.py --executor-file tests/oss/oss_contract.py --executor-file tests/oss/test_oss_contract.py

``oss_contract.py`` reuses the accepted NEWAPP-002 helpers (``tests/config/env_contract.py``) for the
names-only environment reader, the value leak guard, the repository scanner self-check and the
controller path-guard mirror, so each guard has exactly one implementation.
"""
