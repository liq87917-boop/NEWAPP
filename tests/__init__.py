"""NEWAPP automated tests.

Layout: ``tests/baseline`` holds repository baseline guards introduced by NEWAPP-001,
``tests/config`` the configuration-contract checks introduced by NEWAPP-002 and ``tests/schema`` the
read-only shared-schema inspection and schema-map checks introduced by NEWAPP-003.
Run everything from the repository root::

    python -m unittest discover -s tests -p "test_*.py"
"""
