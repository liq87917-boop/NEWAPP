# Cline/DeepSeek executor contract

The executor receives exactly one controller-approved task.

- Implement only that task and obey its `depends_on` ordering.
- Follow the supplied allowed paths and protected-path list.
- Do not edit queue state, approvals, controller code, rules, or the task blueprint.
- Do not decide that work is complete; report the files changed, checks run, and any unresolved issue.
- Never expose secret values. Configuration diagnostics may name a missing environment variable but may not include its value.
- Do not connect a mobile client directly to SQL Server or embed OSS credentials.
- Do not add a second master-data database or a NEWERP/NEWAPP synchronization service.
- Never execute destructive SQL, production database changes, production deployments, signing, releases, or production-data tests.
- Use isolated disposable test data and reversible migrations. Shared schema work must stop at the Human Gate boundary declared by the controller.
- Do not commit or push; the controller performs a narrowly scoped checkpoint only after GPT acceptance.

