# MaintainAI

MaintainAI is a Python and Streamlit demonstration application for equipment maintenance triage. It combines deterministic sensor validation, manual evidence retrieval, and configurable local or hosted AI analysis to support technicians with initial issue assessment, manual citations, and draft work-order preparation.

## Project overview

MaintainAI is intended to help maintenance teams do the following:

- record equipment and issue reports
- evaluate sensor readings with deterministic thresholds
- retrieve relevant manual sections from a local Markdown knowledge base
- generate advisory recommendations with required evidence citations
- propose a draft work order for technician review
- track maintenance history and review decisions

The application and bundled manual are demonstration materials. The manual is not manufacturer-verified, sensor thresholds are illustrative, and AI-generated guidance is advisory. A qualified technician must verify evidence and approve any work order; the application does not control equipment.

## Key features

- equipment registration and issue capture
- sensor evaluation for vibration, bearing temperature, and discharge pressure
- Markdown manual retrieval and citation tracking
- Ollama or OpenAI-compatible AI analysis with schema validation and citation checks
- draft work order creation and editable review workflow
- audit history for issue creation, draft edits, approvals, and rejections
- SQLite persistence with isolated, test-specific temporary databases for automated tests

## Architecture and data flow

The core architecture is intentionally small and explicit:

1. Streamlit UI (`app.py`)
   - presents the report issue form, work-order review view, and maintenance history view
   - saves issue records and work-order updates through the database layer

2. Database layer (`src/database.py`)
   - stores equipment, issues, work-orders, and audit events in SQLite
   - manages creation, listing, review, and editing logic
   - enforces that only draft work orders can be edited or reviewed again

3. Rule engine (`src/rules.py`)
   - evaluates deterministic sensor thresholds
   - flags missing, invalid, conflicting, and threshold-exceeding readings
   - returns machine-checkable results without claiming a diagnosis

4. Manual retrieval (`src/retrieval.py`)
   - loads Markdown sections from `data/manuals`
   - searches the manual text for relevant evidence
   - produces citations with traceable source references

5. AI analysis (`src/ai_service.py`)
   - sends issue context, deterministic sensor checks, and retrieved evidence to the configured AI provider
   - requires JSON output matching a strict schema
   - rejects unsupported citations or structurally invalid AI output
   - marks the result as advisory and leaves final approval to a technician
   - keeps analysis results in Streamlit session state; AI analysis is not persisted in SQLite

## Technology stack

- Python 3.13
- Streamlit for the web UI
- SQLite for persistence
- Ollama for local inference by default; an OpenAI-compatible provider is optional
- pytest for automated tests
- Markdown manuals in `data/manuals`

## Local setup (Windows)

From the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If you want to bypass activation, use the venv interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Ollama installation and model setup

This project expects a local Ollama service on `http://localhost:11434` with a model named `qwen2.5:3b` by default.

Recommended Windows setup:

```powershell
winget install Ollama.Ollama
```

Then start Ollama and pull the model:

```powershell
ollama serve
ollama pull qwen2.5:3b
```

The active application defaults to these values in `src/ai_service.py`:

- `OLLAMA_URL = http://localhost:11434`
- `OLLAMA_MODEL = qwen2.5:3b`

You may override them through environment variables in a local `.env` file, for example:

```env
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
```

## Environment configuration and secret management

- Keep local environment variables in a project-local `.env` file.
- Do not commit secrets or personal credentials into source control.
- The repository includes `.env.example` as a template.
- The AI service supports `AI_PROVIDER=ollama` (default), `AI_PROVIDER=openai`, or `AI_PROVIDER=openai_compatible`. For the latter two, provide `OPENAI_API_KEY`, `OPENAI_MODEL`, and optionally `OPENAI_BASE_URL`.
- Persist the SQLite database by setting `MAINTAINAI_DB_PATH`, or by mounting a writable volume to the selected host runtime.
- The app will still allow the user to view saved reports when AI analysis is unavailable; it does not auto-approve work orders.
- The bundled `.env.example` binds Streamlit to loopback. Do not bind to a public interface without adding authentication, access controls, and a secure deployment configuration.

## Hosted deployment and provider selection

The application currently defaults to the local Ollama provider:

```env
AI_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
```

For a remote provider, use:

```env
AI_PROVIDER=openai
OPENAI_API_KEY=your_key
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

A hosted deployment must explicitly configure its service to bind on the interface required by its platform, provide persistent database storage, and add authentication and access controls. The application has no built-in user authentication or role-based access control; hosted deployment has not been verified.

## Launching the Streamlit application

From the project root:

```powershell
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\streamlit.exe run app.py
```

Alternatively, without activation:

```powershell
.\.venv\Scripts\streamlit.exe run app.py
```

The application binds to `127.0.0.1` by default and opens in the default Streamlit browser. It exposes the dashboard, issue-reporting, analysis, work-order review, and maintenance-history views.

After analyzing a saved issue, use **Generate Work Order Draft** on the Analysis Results page to save the validated AI recommendation against that issue. Draft creation is idempotent per issue; if a work order already exists, the existing work-order ID is shown. Drafts remain unapproved until a technician explicitly reviews them on the Work Orders page.

## Running the automated tests

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Project-specific verification scripts also exist:

```powershell
.\.venv\Scripts\python.exe check_rules.py
.\.venv\Scripts\python.exe check_retrieval.py
.\.venv\Scripts\python.exe check_ai.py
```

`check_database.py` uses a temporary database and does not modify `data/maintainai.db`. The `check_ai.py` script sends a request to the configured AI provider; run it only when you intend to make that local or hosted provider call.

## Database tables and audit history

The default SQLite database is created at `data/maintainai.db` unless `MAINTAINAI_DB_PATH` is set.

The project stores the following tables:

- `equipment`
  - equipment_id
  - equipment_type
  - created_at

- `issues`
  - issue_id
  - equipment_id
  - description
  - operating_events
  - sensor_readings
  - observations
  - possible_causes
  - confirmed_findings
  - created_at

- `work_orders`
  - work_order_id
  - issue_id
  - draft_json
  - status (`draft`, `approved`, `rejected`, `completed`)
  - technician_notes
  - reviewed_by
  - reviewed_at
  - created_at

- `audit_events`
  - event_id
  - issue_id
  - work_order_id
  - event_type
  - details
  - created_at

Audit events include issue creation, work-order drafting, draft edits, approval decisions, and rejection decisions.

## Technician approval and rejection workflow

The application supports this workflow:

- a draft work order is created for an issue
- a technician can review the draft and record an explicit decision
- valid decisions are `approved` or `rejected`
- once a work order is approved or rejected, it cannot be reviewed again
- only draft work orders may be edited
- all decisions are persisted in the database and recorded in `audit_events`

This prevents silent approval or duplicate review actions.

## Manual retrieval and citation handling

The retrieval layer reads Markdown manuals from `data/manuals` and breaks them into sections. Each section retains the source filename, heading, and line numbers. Search results include a citation string that matches the retrieved evidence and can be displayed to the user.

The AI service enforces strict citation validation:

- it only accepts citations that exactly match the retrieved evidence
- it rejects fabricated citations
- it rejects structurally invalid or incomplete AI output
- it treats AI output as advisory only and never approves the work order automatically

## Deterministic sensor rules

The rule engine in `src/rules.py` evaluates readings for:

- vibration (`vibration_mm_s`)
- bearing temperature (`bearing_temperature_c`)
- discharge pressure (`discharge_pressure_bar`)

It flags:

- missing readings
- invalid values
- conflicting values across multiple readings
- readings above configured demo limits

Important: the threshold values used by the project are demo values for the application workflow and are not verified equipment safety limits. They are illustrative only and must not be treated as a real manufacturer or engineering specification.

## Known limitations

- The app is designed for local demonstration and maintenance coordination, not remote equipment control.
- The AI workflow depends on a reachable local Ollama instance.
- The AI output is advisory and always requires technician review and approval.
- There is no production-grade hosted deployment in this repository. Any hosted deployment would require a reachable inference service, secure configuration, and production hardening.
- The app intentionally does not auto-approve or auto-execute maintenance actions.

## Deployment instructions and required configuration

This repository does not include a tested hosted deployment. To deploy it in a more production-like environment, the following must be configured:

- a persistent SQLite database or a managed database backend
- a reachable Ollama endpoint or an equivalent model-serving service
- environment variables such as `OLLAMA_URL` and `OLLAMA_MODEL`
- secure handling of secrets and local configuration files
- reverse proxy or app runtime configuration if hosting in a shared environment

Use a local or secure network-only deployment model until the runtime is validated in the target environment.

## Completed functionality versus excluded scope

Completed in this repository:

- issue reporting and history
- deterministic sensor validation
- manual retrieval and evidence citation
- staff review workflow for work orders
- SQLite persistence and auditing
- automated tests for rules, retrieval, AI validation, and work-order lifecycle
- local Streamlit UI

Excluded from the current scope:

- remote equipment control or automatic maintenance activation
- production-grade distributed deployment
- verified manufacturer safety-limit configuration
- hosted deployment verification
- enterprise-grade authentication or RBAC

## Operational and deployment limitations

- AI analysis is advisory, session-scoped, and is not retained in the database.
- The bundled manual and sensor limits are illustrative and not manufacturer-verified.
- SQLite contains issue, work-order, and audit history. Backups and schema migration tooling are not provided.
- Streamlit's local development server is not a production deployment. Authentication, authorization, deployment hardening, and hosted-provider availability have not been verified.
- Automated tests use isolated temporary databases; they do not certify a live AI provider or deployed environment.
