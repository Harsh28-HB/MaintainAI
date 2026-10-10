# MaintainAI verification notes

This document records project-specific operating and verification information. It does not describe an external assessment or imply production certification.

## AI and data handling

- AI providers are selected with `AI_PROVIDER`: local Ollama is the default; `openai` and `openai_compatible` are also supported.
- AI output is schema- and citation-validated and remains advisory. A technician must explicitly review work orders.
- Full AI analysis is held in Streamlit session state and is not persisted. SQLite stores equipment, issue, work-order, and audit records.
- The bundled pump reference and sensor thresholds are illustrative, not manufacturer-verified.
- `check_ai.py` contacts the configured provider. It was not run as part of the current repository audit.

## Safe local validation

- Run the automated suite with `.\.venv\Scripts\python.exe -m pytest -q`.
- `check_rules.py` and `check_retrieval.py` validate local deterministic functionality.
- `check_database.py` creates and removes an isolated temporary database; it does not write to the configured application database.
- Keep `.env` and `data/maintainai.db` private. Automated database tests use temporary SQLite files.

## Current environment and scope

- The project was inspected in the existing Windows workspace with its `.venv` Python environment.
- Hosted deployment, authentication/authorization, backups, and database migrations are not provided or certified.
- The Streamlit development server binds to loopback by default. A network-facing deployment requires separately configured access controls and security review.
- Automated tests do not verify provider availability, model quality, manufacturer limits, or deployed infrastructure.

Record test and browser results in the task report only after actually running those checks; do not retain stale test counts here.
