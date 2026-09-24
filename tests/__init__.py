"""NEWAPP automated tests.

Layout: ``tests/baseline`` holds repository baseline guards introduced by NEWAPP-001,
``tests/config`` the configuration-contract checks introduced by NEWAPP-002, ``tests/schema`` the
read-only shared-schema inspection and schema-map checks introduced by NEWAPP-003 and ``tests/oss``
the shared OSS contract checks introduced by NEWAPP-004. ``tests/console`` holds the status-console
contract checks introduced by NEWAPP-006.
Run everything from the repository root::

    python -m unittest discover -s tests -p "test_*.py"
"""
