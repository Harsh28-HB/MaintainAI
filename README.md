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

The persisted `draft` work-order state is shown in the interface as **Pending
Review**. Approval applies only to the documented maintenance work and never
establishes that equipment is safe or authorizes equipment operation.
Operational safety is not established by this application.

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
- The analysis service supports `AI_PROVIDER=ollama` (default), `AI_PROVIDER=demo`, `AI_PROVIDER=openai`, or `AI_PROVIDER=openai_compatible`. Hosted model providers require `OPENAI_API_KEY`, `OPENAI_MODEL`, and optionally `OPENAI_BASE_URL`.
- Persist the SQLite database by setting `MAINTAINAI_DB_PATH`, or by mounting a writable volume to the selected host runtime.
- The app will still allow the user to view saved reports when AI analysis is unavailable; it does not auto-approve work orders.
- The bundled `.env.example` binds Streamlit to loopback. Do not bind to a public interface without adding authentication, access controls, and a secure deployment configuration.

## Streamlit Community Cloud deployment and provider selection

Local development defaults to Ollama:

```env
AI_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
```

For a keyless Streamlit Community Cloud demo, set the app's **Settings >
Secrets** to:

```toml
AI_PROVIDER = "demo"
```

Demo mode makes no external AI requests and requires no API credentials. It
uses deterministic sensor rules and any retrieved manual passages to produce
clearly labelled technician-review guidance; it does not generate or infer
failure causes. If retrieval finds no manual evidence, the guidance explicitly
states that it has no manual support and includes no citations. The UI displays:

> Demo Mode: deterministic guidance only. No generative AI is used.

For genuine hosted model analysis, configure OpenAI in Streamlit secrets.
Replace the placeholder values with credentials and a model available to your
account; never commit a real key:

```toml
AI_PROVIDER = "openai"
OPENAI_API_KEY = "replace-with-your-provider-key"
OPENAI_MODEL = "gpt-4o-mini"
```

`OPENAI_BASE_URL` is optional for OpenAI. An OpenAI-compatible service may be
configured explicitly with:

```toml
AI_PROVIDER = "openai_compatible"
OPENAI_API_KEY = "replace-with-your-provider-key"
OPENAI_MODEL = "provider-model-name"
OPENAI_BASE_URL = "https://your-provider.example/v1"
```

The application reads root-level Streamlit secrets first, then environment
variables, then the documented default. This lets an explicitly configured
Cloud provider such as `AI_PROVIDER = "demo"` take effect even if the runtime
also has a provider environment variable. Local `.env` and PowerShell
environment configuration continue to work when the corresponding Streamlit
secret is not set. Restart the app after changing secrets or environment
configuration.
`AI_PROVIDER=ollama` remains the local default when the provider is unset.
Ollama running on your development computer is not reachable by a Community
Cloud app through `localhost`.

For local development, set the provider explicitly in `.env`:

```env
AI_PROVIDER=openai
OPENAI_API_KEY=your-provider-key
OPENAI_MODEL=gpt-4o-mini
```

To use local Ollama instead:

```env
AI_PROVIDER=ollama
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
```

Because provider settings are loaded when the AI service module is imported,
stop and restart the Streamlit server after editing `.env` or changing secrets.
The AI service logs the selected provider name only and never logs credentials.

Deployment steps:

1. Ensure the GitHub repository contains `app.py`, `requirements.txt`, `src/`,
   and `data/manuals/`.
2. In Streamlit Community Cloud, create an app for `Harsh28-HB/MaintainAI`
   and set the entry point to `app.py`.
3. Add `AI_PROVIDER = "demo"` in **Settings > Secrets** for the no-key demo,
   or configure the OpenAI secrets above for genuine hosted inference.
4. Restart/redeploy after changing secrets, then submit an issue to verify
   analysis behavior. Demo mode should show its deterministic-guidance notice.
   Keep any provider key only in the secrets editor; never commit
   `.streamlit/secrets.toml`.

The configured OpenAI-compatible service must support chat completions and
JSON-object response formatting. MaintainAI validates the returned schema and
retrieved-manual citations before displaying an analysis. Findings remain
advisory, and work orders still require technician review.

Streamlit Community Cloud's local filesystem is not durable storage. This app
currently uses SQLite, so records may be lost when the app is restarted or
redeployed; use durable database/storage before relying on hosted records. The
app also has no built-in authentication or role-based access control. Hosted
deployment, provider availability, and production security have not been
verified.

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
- from Work Orders, use **Create Work Order Draft** when a saved issue does
  not yet have a work order; the draft is persisted against that issue and
  appears in the same view immediately
- repeated creation requests for the same issue return its existing order
  rather than creating a duplicate
- a technician can review the draft and record an explicit decision
- valid decisions are `approved` or `rejected`
- the interface labels a stored `draft` as **Pending Review**
- an approved order is labelled **Approved for maintenance work**; this is not
  permission to operate equipment
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

Missing, invalid, and conflicting measurements are listed individually in
Analysis Results. Obtain and verify those readings and have a qualified
technician review the issue. The application reports **Operational safety not
established** because it has no applicable, verified equipment-specific
operating rule; neither generated guidance nor work-order approval changes
that status.

## Known limitations

- The app is designed for local demonstration and maintenance coordination, not remote equipment control.
- The analysis workflow requires deterministic `demo` mode, a reachable local
  Ollama service, or a reachable hosted provider configured with valid
  credentials.
- The AI output is advisory and always requires technician review and approval.
- Neither analysis guidance nor an approved work order is equipment-operation authorization.
- There is no production-grade hosted deployment in this repository. Any hosted deployment would require a reachable inference service, secure configuration, and production hardening.
- The app intentionally does not auto-approve or auto-execute maintenance actions.

## Deployment instructions and required configuration

The Community Cloud instructions above configure the application runtime and
hosted AI provider, but do not make the app production-ready. Before using it
with real operational records, address the following:

- durable database storage or a managed database backend
- authentication and access controls for intended users
- secure handling of provider secrets and local configuration files
- operational monitoring, backups, and recovery procedures

Validate provider, storage, and access-control configuration in the target
environment before relying on a deployment.

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
- production-grade hosted deployment verification
- enterprise-grade authentication or RBAC

## Operational and deployment limitations

- AI analysis is advisory, session-scoped, and is not retained in the database.
- The bundled manual and sensor limits are illustrative and not manufacturer-verified.
- SQLite contains issue, work-order, and audit history. Backups and schema migration tooling are not provided.
- Authentication, authorization, deployment hardening, durable hosted storage, and hosted-provider availability have not been verified.
- Automated tests use isolated temporary databases; they do not certify a live AI provider or deployed environment.
