import logging
import json
import math
from html import escape

import streamlit as st

from src.database import (
    init_db,
    register_equipment,
    create_issue,
    create_work_order_once,
    create_analysis_work_order_once,
    update_work_order_draft,
    review_work_order,
    get_issue,
    get_issue_options,
    get_issue_history,
    get_work_orders,
)
from src.dashboard import equipment_health_state, get_dashboard_summary
from src.rules import evaluate_sensor_readings
from src.retrieval import search_manuals
from src.ai_service import (
    AI_PROVIDER,
    DEMO_MODE_NOTICE,
    OPENAI_API_KEY,
    AIServiceError,
    analyze_issue,
)
from src.issue_diagnostics import report_issue_workflow_error
from src.work_order_drafts import draft_from_analysis, draft_from_issue

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("maintainai.app")

st.set_page_config(
    page_title="MaintainAI",
    page_icon="🔧",
    layout="wide",
)

st.markdown(
    """
    <style>
        :root {
            --navy-950: #0B1220;
            --navy-900: #0F172A;
            --navy-800: #172235;
            --navy-700: #1E293B;
            --indigo: #6366F1;
            --teal-600: #14B8A6;
            --teal-500: #2DD4BF;
            --soft-bg: #0B1220;
            --card: #172235;
            --card-alt: #1E293B;
            --ink: #F8FAFC;
            --muted: #94A3B8;
            --field-label: #CBD5E1;
            --field-bg: #1E293B;
            --field-border: #475569;
            --line: #334155;
            --success: #22C55E;
            --warning: #F59E0B;
            --danger: #EF4444;
            --shadow: 0 12px 30px rgba(0, 0, 0, 0.18);
        }

        .stApp {
            background: var(--soft-bg);
            color: var(--ink);
        }

        [data-testid="stHeader"],
        [data-testid="stToolbar"] {
            background: rgba(11, 18, 32, 0.96);
        }

        section[data-testid="stMain"] {
            background: var(--soft-bg);
            color: var(--ink);
        }

        section[data-testid="stMain"] [data-testid="stMarkdownContainer"],
        section[data-testid="stMain"] [data-testid="stMarkdownContainer"] p,
        section[data-testid="stMain"] [data-testid="stCaptionContainer"] {
            color: var(--ink);
        }

        section[data-testid="stMain"] [data-testid="stCaptionContainer"] {
            color: var(--muted);
        }

        section[data-testid="stMain"] h1,
        section[data-testid="stMain"] h2,
        section[data-testid="stMain"] h3 {
            color: var(--ink);
        }

        section[data-testid="stMain"] [data-testid="stWidgetLabel"],
        section[data-testid="stMain"] [data-testid="stWidgetLabel"] p,
        section[data-testid="stMain"] label,
        section[data-testid="stMain"] [data-testid="stMarkdownContainer"] label {
            color: var(--field-label) !important;
        }

        section[data-testid="stMain"] [data-testid="stTextArea"] textarea,
        section[data-testid="stMain"] [data-testid="stTextInput"] input,
        section[data-testid="stMain"] [data-testid="stNumberInput"] input {
            background-color: var(--field-bg) !important;
            color: var(--ink) !important;
            -webkit-text-fill-color: var(--ink) !important;
            border: 1px solid var(--field-border) !important;
            border-radius: 10px !important;
            caret-color: var(--teal-600);
        }

        section[data-testid="stMain"] [data-testid="stTextArea"] textarea::placeholder,
        section[data-testid="stMain"] [data-testid="stTextInput"] input::placeholder,
        section[data-testid="stMain"] [data-testid="stNumberInput"] input::placeholder {
            color: var(--muted) !important;
            -webkit-text-fill-color: var(--muted) !important;
            opacity: 1;
        }

        section[data-testid="stMain"] [data-testid="stTextArea"] textarea:focus,
        section[data-testid="stMain"] [data-testid="stTextInput"] input:focus,
        section[data-testid="stMain"] [data-testid="stNumberInput"] input:focus {
            border-color: var(--teal-600) !important;
            box-shadow: 0 0 0 2px rgba(20,184,166,0.2) !important;
            outline: none !important;
        }

        section[data-testid="stMain"] [data-testid="stSelectbox"] [role="group"] {
            background-color: var(--field-bg) !important;
            color: var(--ink);
            border-color: var(--field-border) !important;
            border-radius: 10px !important;
            min-height: 2.7rem;
            border: 1px solid var(--field-border) !important;
        }

        section[data-testid="stMain"] [data-testid="stSelectbox"] input[role="combobox"] {
            background-color: var(--field-bg) !important;
            color: var(--ink) !important;
            -webkit-text-fill-color: var(--ink) !important;
        }

        section[data-testid="stMain"] [data-testid="stSelectbox"] [role="group"]:focus-within {
            border-color: var(--teal-600) !important;
            box-shadow: 0 0 0 2px rgba(20,184,166,0.2) !important;
        }

        section[data-testid="stMain"] [data-baseweb="select"] > div {
            background-color: var(--field-bg) !important;
            color: var(--ink) !important;
            border-color: var(--field-border) !important;
            border-radius: 10px !important;
        }

        section[data-testid="stMain"] [data-baseweb="select"] input,
        section[data-testid="stMain"] [data-baseweb="select"] [role="combobox"] {
            color: var(--ink) !important;
            -webkit-text-fill-color: var(--ink) !important;
        }

        [data-baseweb="popover"] [role="listbox"],
        [data-baseweb="popover"] [role="listbox"] [role="option"] {
            background-color: #1E293B !important;
            color: #F8FAFC !important;
        }

        [data-baseweb="popover"] [role="listbox"] [role="option"]:hover,
        [data-baseweb="popover"] [role="listbox"] [role="option"][aria-selected="true"] {
            background-color: #334155 !important;
            color: #FFFFFF !important;
        }

        section[data-testid="stMain"] [data-testid="stRadio"] label,
        section[data-testid="stMain"] [data-testid="stCheckbox"] label {
            color: var(--field-label) !important;
        }

        section[data-testid="stMain"] [data-testid="stRadio"] input[type="radio"],
        section[data-testid="stMain"] [data-testid="stCheckbox"] input[type="checkbox"] {
            accent-color: var(--indigo);
        }

        section[data-testid="stMain"] [data-testid="stRadio"] label:focus-within,
        section[data-testid="stMain"] [data-testid="stCheckbox"] label:focus-within {
            outline: 2px solid rgba(99,102,241,0.65);
            outline-offset: 2px;
            border-radius: 4px;
        }

        section[data-testid="stMain"] [data-testid="stExpander"] details {
            background: var(--card) !important;
            border: 1px solid var(--line) !important;
            border-radius: 12px !important;
            overflow: hidden;
        }

        section[data-testid="stMain"] [data-testid="stExpander"] summary {
            background: var(--card) !important;
            color: var(--ink) !important;
            min-height: 2.8rem;
            transition: background-color 120ms ease;
        }

        section[data-testid="stMain"] [data-testid="stExpander"] summary:hover {
            background: var(--card-alt) !important;
        }

        section[data-testid="stMain"] [data-testid="stExpander"] summary:focus-visible {
            outline: 3px solid rgba(99,102,241,0.65) !important;
            outline-offset: -3px;
        }

        section[data-testid="stMain"] [data-testid="stExpander"] summary p,
        section[data-testid="stMain"] [data-testid="stExpander"] summary span {
            color: var(--ink) !important;
            -webkit-text-fill-color: var(--ink) !important;
        }

        section[data-testid="stMain"] [data-testid="stExpander"] summary [data-testid="stIconMaterial"],
        section[data-testid="stMain"] [data-testid="stExpander"] summary svg {
            color: var(--muted) !important;
            fill: var(--muted) !important;
        }

        section[data-testid="stMain"] [data-testid="stExpander"] [data-testid="stExpanderDetails"] {
            background: var(--card) !important;
            border-top: 1px solid var(--line);
            color: var(--field-label) !important;
            padding: 0.85rem 1rem;
        }

        section[data-testid="stMain"] [data-testid="stExpander"] [data-testid="stExpanderDetails"] p,
        section[data-testid="stMain"] [data-testid="stExpander"] [data-testid="stExpanderDetails"] span {
            color: var(--field-label) !important;
        }

        section[data-testid="stMain"] [data-testid="stJson"] .react-json-view {
            background: var(--field-bg) !important;
            border: 1px solid var(--line);
            border-radius: 10px;
            color: var(--field-label) !important;
            padding: 0.5rem;
        }

        section[data-testid="stMain"] [data-testid="stJson"] .react-json-view * {
            color: var(--field-label) !important;
        }

        section[data-testid="stMain"] [data-testid="stAlertContainer"] {
            border: 1px solid transparent;
            border-radius: 12px;
            color: var(--field-label) !important;
        }

        section[data-testid="stMain"] [data-testid="stAlertContainer"] p,
        section[data-testid="stMain"] [data-testid="stAlertContainer"] span,
        section[data-testid="stMain"] [data-testid="stAlertContainer"] svg {
            color: inherit !important;
            fill: currentColor !important;
        }

        section[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {
            background: #422F12 !important;
            border-color: #8A5A16 !important;
            color: #FCD34D !important;
        }

        section[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {
            background: #123B2B !important;
            border-color: #1A6848 !important;
            color: #86EFAC !important;
        }

        section[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {
            background: #4A2027 !important;
            border-color: #7A303D !important;
            color: #FECACA !important;
        }

        section[data-testid="stMain"] [data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {
            background: #172B49 !important;
            border-color: #2B4773 !important;
            color: #BFDBFE !important;
        }

        .stSidebar {
            background: var(--navy-900);
        }

        section[data-testid="stSidebar"] {
            width: 17rem !important;
            min-width: 17rem !important;
            max-width: 17rem !important;
        }

        .brand-box {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 16px;
            padding: 1rem 1rem 0.9rem;
            margin-bottom: 1rem;
        }

        .brand-box h1 {
            color: #F8FAFC;
            font-weight: 700;
            letter-spacing: 0.02em;
            margin: 0 0 0.15rem 0;
            font-size: 1.8rem;
        }

        .brand-box p {
            color: var(--muted);
            margin: 0;
            font-size: 0.82rem;
        }

        .sidebar-section {
            color: var(--muted);
            font-size: 0.72rem;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            margin: 1rem 0 0.5rem;
        }

        .nav-label {
            color: #CBD5E1;
            font-weight: 600;
        }

        section[data-testid="stSidebar"] [data-testid="stWidgetLabel"],
        section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
        section[data-testid="stSidebar"] [data-testid="stRadio"] label,
        section[data-testid="stSidebar"] [data-testid="stRadio"] label p,
        section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
            color: #CBD5E1 !important;
        }

        .block-container {
            padding-top: 3.2rem;
            padding-bottom: 2rem;
        }

        .page-header {
            margin-bottom: 1rem;
        }

        .page-header h1 {
            margin: 0;
            color: var(--ink);
            font-weight: 800;
            letter-spacing: -0.03em;
        }

        .page-header p {
            margin: 0.2rem 0 0 0;
            color: var(--muted);
            font-size: 0.95rem;
        }

        .dashboard-heading {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            margin: 0.2rem 0 1.35rem;
        }

        .dashboard-heading h1 {
            color: var(--ink);
            font-size: clamp(1.65rem, 3vw, 2.15rem);
            font-weight: 780;
            letter-spacing: -0.035em;
            margin: 0;
        }

        .dashboard-heading p {
            color: var(--muted);
            font-size: 0.94rem;
            margin: 0.35rem 0 0;
        }

        .dashboard-eyebrow {
            color: var(--teal-600);
            font-size: 0.68rem;
            font-weight: 800;
            letter-spacing: 0.11em;
            margin-bottom: 0.3rem;
        }

        .dashboard-date {
            align-self: flex-start;
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 999px;
            color: #CBD5E1;
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.48rem 0.75rem;
            white-space: nowrap;
        }

        .dashboard-section-heading {
            color: var(--ink);
            font-size: 0.95rem;
            font-weight: 750;
            margin: 1.15rem 0 0.6rem;
        }

        @media (max-width: 600px) {
            .dashboard-heading {
                flex-direction: column;
            }
        }

        .kpi-card,
        .info-card,
        .panel {
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 18px;
            box-shadow: var(--shadow);
            padding: 1rem 1.1rem;
        }

        .kpi-card {
            min-height: 132px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            border-top: 3px solid var(--indigo);
        }

        .kpi-card.kpi-issues {
            border-top-color: #38BDF8;
        }

        .kpi-card.kpi-pending {
            border-top-color: var(--warning);
        }

        .kpi-card.kpi-approved {
            border-top-color: var(--success);
        }

        .metric-icon {
            width: 42px;
            height: 42px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(99,102,241,0.14);
            color: #A5B4FC;
            font-size: 1.2rem;
            margin-bottom: 0.7rem;
        }

        .metric-label {
            color: var(--muted);
            font-size: 0.79rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .metric-value {
            color: var(--ink);
            font-size: clamp(1.35rem, 2vw, 2rem);
            font-weight: 800;
            margin-top: 0.35rem;
            line-height: 1.1;
            overflow-wrap: anywhere;
        }

        .metric-detail {
            color: var(--muted);
            font-size: 0.72rem;
            line-height: 1.35;
            margin-top: 0.45rem;
        }

        .kpi-critical {
            border-top-color: var(--danger);
        }

        .kpi-warning {
            border-top-color: var(--warning);
        }

        .kpi-health {
            border-top-color: var(--teal-600);
        }

        .kpi-critical .metric-icon {
            color: #FCA5A5;
            background: rgba(239,68,68,0.14);
        }

        .kpi-warning .metric-icon {
            color: #FCD34D;
            background: rgba(245,158,11,0.14);
        }

        .status-badge {
            display: inline-block;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.03em;
            padding: 0.3rem 0.6rem;
            border-radius: 999px;
            border: 1px solid transparent;
            text-transform: uppercase;
        }

        .status-draft {
            background: rgba(245,158,11,0.12);
            color: #FCD34D;
            border-color: rgba(245,158,11,0.25);
        }

        .status-approved {
            background: rgba(34,197,94,0.12);
            color: #86EFAC;
            border-color: rgba(34,197,94,0.25);
        }

        .status-rejected {
            background: rgba(239,68,68,0.12);
            color: #FCA5A5;
            border-color: rgba(239,68,68,0.25);
        }

        .status-completed {
            background: rgba(34,197,94,0.12);
            color: #86EFAC;
            border-color: rgba(34,197,94,0.25);
        }

        .priority-high {
            background: rgba(245,158,11,0.12);
            color: #FCD34D;
            border-color: rgba(245,158,11,0.25);
        }

        .priority-medium {
            background: rgba(20,184,166,0.12);
            color: #5EEAD4;
            border-color: rgba(20,184,166,0.25);
        }

        .priority-routine,
        .priority-requires_review {
            background: rgba(148,163,184,0.12);
            color: #CBD5E1;
            border-color: rgba(148,163,184,0.22);
        }

        .priority-badge {
            display: inline-block;
            color: #CBD5E1;
            background: rgba(148,163,184,0.08);
            border: 1px solid rgba(148,163,184,0.22);
            border-radius: 6px;
            font-size: 0.75rem;
            padding: 0.2rem 0.45rem;
        }

        .priority-urgent {
            background: rgba(239,68,68,0.12);
            color: #FCA5A5;
            border-color: rgba(239,68,68,0.25);
        }

        .section-title {
            color: var(--ink);
            font-weight: 700;
            font-size: 1.1rem;
            margin: 0 0 0.7rem 0;
        }

        .muted {
            color: var(--muted);
        }

        .empty-state {
            background: rgba(30,41,59,0.65);
            border: 1px dashed #475569;
            border-radius: 16px;
            padding: 1.25rem;
            color: var(--muted);
        }

        .data-row {
            padding: 0.5rem 0;
            border-bottom: 1px solid var(--line);
        }

        .data-row:last-child {
            border-bottom: none;
        }

        .st-key-recent-activity-panel,
        .st-key-equipment-health-panel,
        .st-key-dashboard-chart-panel,
        .st-key-dashboard-equipment-panel,
        .st-key-dashboard-orders-panel,
        .st-key-dashboard-activity-panel {
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 18px;
            box-shadow: var(--shadow);
            padding: 1rem 1.15rem;
        }

        .st-key-dashboard-chart-panel {
            min-height: 320px;
            margin-bottom: 1rem;
        }

        .st-key-dashboard-equipment-panel,
        .st-key-dashboard-orders-panel {
            min-height: 340px;
        }

        .st-key-dashboard-activity-panel {
            padding-top: 0.35rem;
        }

        .dashboard-panel-title {
            color: var(--ink);
            font-size: 1.02rem;
            font-weight: 750;
            margin: 0 0 0.25rem;
        }

        .dashboard-panel-caption {
            color: var(--muted);
            font-size: 0.82rem;
            margin-bottom: 0.75rem;
        }

        .chart-metric-title {
            color: var(--field-label);
            font-size: 0.82rem;
            font-weight: 700;
            margin: 0.4rem 0 0.2rem;
        }

        .activity-item {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 0.5rem 0.85rem;
            align-items: center;
            padding: 0.78rem 0;
            border-bottom: 1px solid var(--line);
        }

        .activity-item:last-child {
            border-bottom: 0;
        }

        .activity-title {
            color: var(--ink);
            font-weight: 650;
            font-size: 0.9rem;
            overflow-wrap: anywhere;
        }

        .activity-meta {
            color: var(--muted);
            font-size: 0.76rem;
            margin-top: 0.15rem;
        }

        .activity-status {
            background: #1E293B;
            border: 1px solid #475569;
            border-radius: 999px;
            color: #CBD5E1;
            font-size: 0.67rem;
            font-weight: 750;
            letter-spacing: 0.035em;
            padding: 0.28rem 0.55rem;
            text-transform: uppercase;
            white-space: nowrap;
        }

        .activity-status.status-warning {
            color: #FCD34D;
            background: #422F12;
            border-color: #8A5A16;
        }

        .activity-status.status-critical {
            color: #FCA5A5;
            background: #4A2027;
            border-color: #7A303D;
        }

        .activity-status.status-success {
            color: #86EFAC;
            background: #123B2B;
            border-color: #1A6848;
        }

        .activity-status.status-normal {
            color: #86EFAC;
            background: #123B2B;
            border-color: #1A6848;
        }

        .activity-status.status-unknown {
            color: #CBD5E1;
            background: #1E293B;
            border-color: #475569;
        }

        .equipment-item {
            padding: 0.8rem 0;
            border-bottom: 1px solid var(--line);
        }

        .equipment-item:last-child {
            border-bottom: 0;
        }

        .equipment-item-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.75rem;
        }

        .equipment-name {
            color: var(--ink);
            font-weight: 700;
            overflow-wrap: anywhere;
        }

        .work-order-row {
            border-bottom: 1px solid var(--line);
            padding: 0.75rem 0;
        }

        .work-order-row:last-of-type {
            border-bottom: 0;
        }

        .work-order-summary {
            color: var(--ink);
            font-size: 0.86rem;
            font-weight: 650;
            margin-top: 0.38rem;
            overflow-wrap: anywhere;
        }

        .quick-action-card {
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 16px;
            min-height: 80px;
            padding: 0.85rem 1rem;
            box-shadow: 0 4px 14px rgba(0,0,0,0.16);
        }

        .quick-action-card p {
            color: var(--muted);
            font-size: 0.8rem;
            margin: 0.2rem 0 0;
        }

        @media (max-width: 760px) {
            .block-container {
                padding-left: 1rem;
                padding-right: 1rem;
            }

            .kpi-card {
                min-height: 112px;
                padding: 0.8rem;
            }

            .metric-value {
                font-size: 1.65rem;
            }

            .dashboard-panel {
                min-height: auto;
                padding: 0.9rem;
            }

            .st-key-dashboard-chart-panel,
            .st-key-dashboard-equipment-panel,
            .st-key-dashboard-orders-panel {
                min-height: auto;
            }

            .activity-item {
                grid-template-columns: 1fr;
            }
        }

        .tiny {
            font-size: 0.76rem;
            color: var(--muted);
        }

        section[data-testid="stMain"] .stButton > button,
        section[data-testid="stMain"] [data-testid="stFormSubmitButton"] button,
        section[data-testid="stMain"] button[data-testid^="stBaseButton-"] {
            min-height: 2.65rem;
            padding: 0.5rem 1rem;
            border: 1px solid var(--indigo) !important;
            border-radius: 11px;
            background: var(--indigo) !important;
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
            font-weight: 700;
            box-shadow: 0 8px 18px rgba(99,102,241,0.22);
            transition: background-color 120ms ease, border-color 120ms ease, box-shadow 120ms ease;
        }

        section[data-testid="stMain"] .stButton > button:hover,
        section[data-testid="stMain"] [data-testid="stFormSubmitButton"] button:hover,
        section[data-testid="stMain"] button[data-testid^="stBaseButton-"]:hover {
            border-color: #4F46E5 !important;
            background: #4F46E5 !important;
            color: #FFFFFF !important;
            -webkit-text-fill-color: #FFFFFF !important;
        }

        section[data-testid="stMain"] .stButton > button:focus-visible,
        section[data-testid="stMain"] [data-testid="stFormSubmitButton"] button:focus-visible,
        section[data-testid="stMain"] button[data-testid^="stBaseButton-"]:focus-visible {
            outline: 3px solid rgba(129,140,248,0.75) !important;
            outline-offset: 2px;
            box-shadow: 0 0 0 2px var(--soft-bg) !important;
        }

        section[data-testid="stMain"] .stButton > button:disabled,
        section[data-testid="stMain"] [data-testid="stFormSubmitButton"] button:disabled,
        section[data-testid="stMain"] button[data-testid^="stBaseButton-"]:disabled {
            border-color: #475569 !important;
            background: #334155 !important;
            color: #CBD5E1 !important;
            -webkit-text-fill-color: #CBD5E1 !important;
            box-shadow: none;
            cursor: not-allowed;
        }

        .stForm {
            padding: 0;
        }

        [data-testid="stForm"]:has([data-testid="stSelectbox"]) {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        [data-testid="stForm"]:has([data-testid="stSelectbox"]) [data-testid="stTextArea"],
        [data-testid="stForm"]:has([data-testid="stSelectbox"]) [data-testid="stTextInput"] {
            margin-bottom: 0.35rem;
        }

        .st-key-sensor-section {
            background: var(--card);
            border: 1px solid var(--line);
            border-radius: 14px;
            padding: 1rem 1rem 0.25rem;
            margin: 0.5rem 0 0.6rem;
        }

        .sensor-section-title {
            color: var(--ink);
            font-weight: 700;
            font-size: 1rem;
            margin: 0 0 0.2rem;
        }

        .issue-submit-row {
            padding-top: 0.65rem;
            border-top: 1px solid var(--line);
            margin-top: 0.25rem;
        }

        .evidence-box {
            background: var(--card-alt);
            border: 1px solid var(--line);
            border-radius: 16px;
            padding: 0.8rem 1rem;
        }

        .alert-box {
            border-left: 4px solid var(--teal-600);
            background: rgba(20,184,166,0.08);
            border-radius: 12px;
            padding: 0.85rem 1rem;
            color: var(--ink);
        }
    </style>
    """,
    unsafe_allow_html=True,
)

init_db()

st.session_state.setdefault("current_page", "Dashboard")
if AI_PROVIDER == "demo":
    st.info(DEMO_MODE_NOTICE)


def work_order_status_label(status: str) -> str:
    normalized = str(status).lower().replace(" ", "_")
    return {
        "draft": "Pending Review",
        "approved": "Approved for maintenance work",
        "rejected": "Rejected",
        "completed": "Completed",
    }.get(normalized, str(status))


def status_badge(status: str) -> str:
    normalized = str(status).lower().replace(" ", "_")
    css = {
        "draft": "status-draft",
        "approved": "status-approved",
        "rejected": "status-rejected",
        "completed": "status-completed",
    }.get(normalized, "status-draft")
    return (
        f'<span class="status-badge {css}">'
        f'{escape(work_order_status_label(status))}</span>'
    )


def priority_badge(priority: str) -> str:
    return (
        f'<span class="priority-badge">Priority: '
        f'{escape(str(priority).replace("_", " ").title())}</span>'
    )


def metric_card(
    title: str,
    value: str,
    icon: str,
    variant: str = "",
    detail: str = "",
) -> None:
    st.markdown(
        f"""
        <div class="kpi-card {variant}">
            <div class="metric-icon">{icon}</div>
            <div class="metric-label">{title}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-detail">{detail}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sensor_results(results):
    st.subheader("Sensor validation and missing readings")
    sensor_results = results.get("results", [])
    review_statuses = {"missing", "invalid", "conflicting"}
    readings_for_review = [
        result
        for result in sensor_results
        if result.get("status") in review_statuses
    ]

    if readings_for_review:
        st.warning(
            "The following measurements are missing, invalid, or conflicting "
            "and need verification:"
        )
        for result in readings_for_review:
            status = result["status"].replace("_", " ").title()
            st.warning(f"{status} measurement — {result['metric']}: {result['message']}")
    elif not sensor_results:
        st.info("No sensor validation results are available.")

    for result in sensor_results:
        if result.get("status") in review_statuses:
            continue
        if result.get("status") == "threshold_exceeded":
            st.warning(
                f"{result['metric']}: {result['message']} "
                "This is an illustrative demo-rule result, not a verified "
                "equipment safety limit."
            )
        else:
            st.write(
                f"**{result['metric']} — {result['status'].replace('_', ' ').title()}**"
            )
            st.caption(
                "This comparison uses an illustrative demo rule only; it "
                "does not establish operational safety."
            )

    st.caption(results.get(
        "note",
        "Demo thresholds are illustrative and are not verified equipment "
        "safety limits.",
    ))


def render_analysis_results_page():
    st.markdown(
        """
        <div class="page-header">
            <h1>Analysis Results</h1>
            <p>Advisory guidance is based on the selected provider, retrieved evidence, and deterministic checks.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "last_analysis" not in st.session_state:
        if AI_PROVIDER == "demo":
            st.info("No demo guidance has been generated yet. Submit an issue from the Report an Issue page.")
        else:
            st.info("No AI analysis has been generated yet. Submit an issue from the Report an Issue page.")
        return

    analysis = st.session_state["last_analysis"]
    evidence = st.session_state.get("last_evidence", [])
    issue = st.session_state.get("last_issue", {})

    if analysis.get("ai_provider") == "demo":
        st.info(DEMO_MODE_NOTICE)
    else:
        st.markdown(
            '<div class="alert-box">AI output is advisory only. It does not approve a work order or authorize equipment operation.</div>',
            unsafe_allow_html=True,
        )

    st.subheader("Issue analysis and available evidence")
    st.markdown('<div class="section-title">Reported issue</div>', unsafe_allow_html=True)
    st.write(issue.get("description", "No issue description available."))

    st.markdown('<div class="section-title">Observations</div>', unsafe_allow_html=True)
    for item in analysis.get("observations", []):
        st.write(f"• {item.get('text', '')}")
        for citation in item.get("citations", []):
            st.caption(f"Evidence: {citation}")

    st.markdown('<div class="section-title">Possible causes (unconfirmed)</div>', unsafe_allow_html=True)
    possible_causes = analysis.get("possible_causes", [])
    if possible_causes:
        for item in possible_causes:
            st.write(f"• {item.get('text', '')}")
            for citation in item.get("citations", []):
                st.caption(f"Evidence: {citation}")
    else:
        st.write("No possible causes were provided.")

    st.markdown('<div class="section-title">Follow-up questions</div>', unsafe_allow_html=True)
    for item in analysis.get("follow_up_questions", []):
        st.write(f"**Q:** {item.get('question', '')}")
        st.caption(item.get("reason", ""))

    st.markdown('<div class="section-title">Priority and rationale (advisory)</div>', unsafe_allow_html=True)
    st.markdown(priority_badge(analysis.get("proposed_priority", "requires_review")), unsafe_allow_html=True)
    st.write(analysis.get("priority_rationale", "No priority rationale was provided."))

    st.markdown('<div class="section-title">Manual evidence</div>', unsafe_allow_html=True)
    if evidence:
        for item in evidence:
            with st.expander(item.get("citation", "Manual evidence")):
                st.markdown(item.get("content", ""))
    else:
        st.info("No manual evidence was available for this issue.")

    st.markdown('<div class="section-title">Evidence limitations</div>', unsafe_allow_html=True)
    limitations = analysis.get("evidence_limitations", [])
    if limitations:
        for item in limitations:
            st.write(f"• {item}")
    else:
        st.write("No explicit evidence limitations were reported.")

    sensor_results = st.session_state.get("last_sensor_results", {})
    if isinstance(sensor_results, dict):
        render_sensor_results(sensor_results)
    else:
        st.warning("Sensor validation data is unavailable and requires review.")

    st.subheader("Recommended next action")
    sensor_findings = [
        result
        for result in sensor_results.get("results", [])
        if result.get("status") in {"missing", "invalid", "conflicting"}
    ] if isinstance(sensor_results, dict) else []
    if sensor_findings:
        st.write("Obtain and verify each measurement listed above:")
        for result in sensor_findings:
            st.write(f"• {result['metric']} — {result['status'].title()}")
    else:
        st.write(
            "Have a qualified technician verify the reported condition, "
            "readings, and applicable site procedure."
        )
    st.write(
        "A qualified technician should review the issue and any cited manual "
        "passages before deciding on maintenance work."
    )
    for item in analysis.get("inspection_steps", []):
        st.write(f"• {item.get('action', '')}")
        st.caption(item.get("reason", ""))
        for citation in item.get("citations", []):
            st.caption(f"Evidence: {citation}")

    issue_id = st.session_state.get("last_issue_id")
    valid_issue_id = (
        isinstance(issue_id, int)
        and not isinstance(issue_id, bool)
        and issue_id > 0
    )
    existing_order = None
    work_order_lookup_failed = False
    if valid_issue_id:
        try:
            existing_orders = get_work_orders(issue_id)
            existing_order = existing_orders[0] if existing_orders else None
        except Exception:
            logger.exception("Could not check for an existing analysis work order")
            work_order_lookup_failed = True

    draft = analysis.get("draft_work_order", {})
    if draft:
        st.markdown('<div class="section-title">Proposed work-order content</div>', unsafe_allow_html=True)
        st.write(draft.get("summary", ""))
        st.markdown(priority_badge(draft.get("priority", "requires_review")), unsafe_allow_html=True)
        for action in draft.get("actions", []):
            st.write(f"• {action}")
        if draft.get("evidence_citations"):
            st.caption("Evidence citations: " + ", ".join(draft["evidence_citations"]))
    else:
        st.info("No proposed work-order content was generated.")

    if not valid_issue_id:
        st.warning(
            "This analysis is not linked to a saved issue, so a work order "
            "cannot be created."
        )
    elif work_order_lookup_failed:
        st.error(
            "Saved work orders could not be checked. Please retry; no new "
            "work order was created."
        )
    elif not existing_order:
        try:
            work_order_draft = draft_from_analysis(analysis)
        except ValueError as exc:
            st.warning(str(exc))
        else:
            if st.button(
                "Save Work Order as Pending Review",
                type="primary",
                key=f"generate-analysis-work-order-{issue_id}",
            ):
                try:
                    work_order_id, created = create_analysis_work_order_once(
                        issue_id,
                        work_order_draft,
                    )
                except (ValueError, TypeError) as exc:
                    st.error(str(exc))
                except Exception:
                    logger.exception(
                        "Could not create analysis work order for issue %s",
                        issue_id,
                    )
                    st.error(
                        "The work-order draft could not be saved. Your issue "
                        "and analysis remain available; please retry."
                    )
                else:
                    if created:
                        existing_order = {
                            "work_order_id": work_order_id,
                            "status": "draft",
                        }
                    else:
                        try:
                            refreshed_orders = get_work_orders(issue_id)
                            existing_order = next(
                                (
                                    order for order in refreshed_orders
                                    if order["work_order_id"] == work_order_id
                                ),
                                None,
                            )
                        except Exception:
                            logger.exception(
                                "Could not refresh status for work order %s",
                                work_order_id,
                            )
                            work_order_lookup_failed = True
                            st.error(
                                "The existing work-order status could not be "
                                "verified. Check Work Orders before proceeding."
                            )
                        if existing_order is None and not work_order_lookup_failed:
                            work_order_lookup_failed = True
                            st.error(
                                "The existing work-order status could not be "
                                "verified. Check Work Orders before proceeding."
                            )
                    st.session_state[f"analysis_work_order_{issue_id}"] = work_order_id
                    if created:
                        st.success(
                            f"Work order #{work_order_id} was saved as "
                            "Pending Review. It has not been approved."
                        )
                    else:
                        st.info(
                            f"Work order #{work_order_id} already exists for "
                            f"issue #{issue_id}; no duplicate was created."
                        )

    st.subheader("Work-order status and required human review")
    if existing_order:
        status = existing_order["status"]
        st.markdown(status_badge(status), unsafe_allow_html=True)
        if status == "draft":
            st.info(
                "A qualified human technician must review this draft before "
                "maintenance work is approved."
            )
        elif status == "approved":
            st.info(
                "Approved for maintenance work only. This is not permission "
                "to operate equipment."
            )
        elif status == "rejected":
            st.warning(
                "This work order was rejected. It is not approved for "
                "maintenance work."
            )
    elif valid_issue_id and not work_order_lookup_failed:
        st.info("No work order has been created for this issue.")

    if existing_order:
        if existing_order["status"] == "draft":
            st.caption(
                "Open Work Orders to edit this pending draft or record a "
                "technician decision. Approval applies to maintenance work only."
            )
        else:
            st.caption(
                "Open Work Orders to inspect this recorded decision. The "
                "decision does not establish equipment-operation safety."
            )
        if st.button(
            "Review Work Orders",
            key=f"review-analysis-work-order-{issue_id}",
        ):
            st.session_state["current_page"] = "Work Orders"
            st.session_state["last_issue_id"] = issue_id
            st.session_state["work_orders_issue_id"] = issue_id
            st.rerun()

    st.subheader("Safety limitation")
    st.warning(
        "Operational safety not established. MaintainAI has no verified, "
        "equipment-specific rule here to determine that this equipment is "
        "safe or unsafe. Generated guidance and work-order approval do not "
        "authorize equipment operation."
    )


def render_dashboard_page():
    try:
        summary = get_dashboard_summary()
    except Exception:
        logger.exception("Could not load the dashboard summary")
        st.error("Dashboard data could not be loaded. Check the application logs and try again.")
        return
    health_states = [equipment_health_state(item) for item in summary["equipment_health"]]
    critical_count = sum(state[0] == "Critical" for state in health_states)
    warning_count = sum(state[0] == "Warning" for state in health_states)
    normal_count = sum(state[0] == "Normal" for state in health_states)
    unknown_count = sum(state[0] == "Unknown" for state in health_states)

    if critical_count:
        health_label = f"{critical_count} Critical"
        health_detail = (
            f"Demo threshold alert · {normal_count} normal · "
            f"{warning_count} review · "
            f"{unknown_count} unknown"
        )
        health_variant = "kpi-critical"
    elif warning_count:
        health_label = f"{warning_count} Review"
        health_detail = (
            f"Demo checks · {normal_count} normal · "
            f"{critical_count} critical · "
            f"{unknown_count} unknown"
        )
        health_variant = "kpi-warning"
    elif normal_count:
        health_label = f"{normal_count} Within limits"
        health_detail = f"{unknown_count} without sensor readings"
        health_variant = "kpi-health"
    else:
        health_label = "Unknown"
        health_detail = "No stored sensor checks"
        health_variant = "kpi-health"

    st.markdown(
        f"""
        <div class="dashboard-heading">
            <div>
                <div class="dashboard-eyebrow">MAINTENANCE INTELLIGENCE</div>
                <h1>Maintenance Overview</h1>
                <p>Equipment insights and maintenance operations from saved records</p>
            </div>
            <div class="dashboard-date">DATA CHECKED&nbsp; · &nbsp;{escape(summary["snapshot_at"])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if st.button("↻  Refresh dashboard", key="refresh-dashboard"):
        st.rerun()

    metric_columns = st.columns(4, gap="small", width="stretch")
    with metric_columns[0]:
        metric_card(
            "Registered equipment",
            str(summary["equipment_count"]),
            "⚙",
            "kpi-equipment",
            "Equipment records",
        )
    with metric_columns[1]:
        metric_card(
            "Reported issues",
            str(summary["issue_count"]),
            "!",
            "kpi-issues",
            "Issue records · no lifecycle status stored",
        )
    with metric_columns[2]:
        metric_card(
            "Pending work orders",
            str(summary["draft_count"]),
            "▤",
            "kpi-pending",
            "Awaiting technician review",
        )
    with metric_columns[3]:
        metric_card(
            "Equipment health",
            health_label,
            "◉",
            health_variant,
            health_detail,
        )

    action_columns = st.columns([1, 1, 1, 3], gap="small")
    actions = [
        (action_columns[0], "Report an Issue", "Report an Issue", "dashboard-report"),
        (action_columns[1], "Review Work Orders", "Work Orders", "dashboard-work-orders"),
        (action_columns[2], "Maintenance History", "Maintenance History", "dashboard-history"),
    ]
    for column, label, page_name, key in actions:
        with column:
            if st.button(label, key=key, width="stretch"):
                st.session_state["current_page"] = page_name
                if page_name == "Work Orders":
                    pending = next(
                        (order for order in summary["work_orders"] if order["status"] == "draft"),
                        None,
                    )
                    if pending:
                        st.session_state["last_issue_id"] = pending["issue_id"]
                        st.session_state["work_orders_issue_id"] = pending["issue_id"]
                st.rerun()

    st.markdown(
        '<div class="dashboard-section-heading">Equipment Health Monitoring</div>',
        unsafe_allow_html=True,
    )
    with st.container(key="dashboard-chart-panel"):
        st.markdown(
            '<div class="dashboard-panel-caption">Stored sensor readings by issue report · illustrative thresholds only</div>',
            unsafe_allow_html=True,
        )
        trend_rows = summary["sensor_trends"]
        metric_labels = {
            "vibration_mm_s": "Vibration (mm/s)",
            "bearing_temperature_c": "Bearing temperature (°C)",
            "discharge_pressure_bar": "Discharge pressure (bar)",
        }
        chart_series = {
            key: [
                {"Timestamp": row["Timestamp"], "Value": row[key]}
                for row in trend_rows
                if key in row
            ]
            for key in metric_labels
        }
        available_series = [
            (key, values) for key, values in chart_series.items() if values
        ]
        if available_series:
            metric_columns = st.columns(3, gap="medium")
            trend_drawn = False
            for index, (key, values) in enumerate(available_series):
                with metric_columns[index]:
                    st.markdown(
                        f'<div class="chart-metric-title">{escape(metric_labels[key])}</div>',
                        unsafe_allow_html=True,
                    )
                    distinct_timestamps = {
                        point["Timestamp"] for point in values
                    }
                    if len(values) > 1 and len(distinct_timestamps) > 1:
                        trend_drawn = True
                        st.line_chart(
                            [
                                {
                                    "Timestamp": point["Timestamp"],
                                    metric_labels[key]: point["Value"],
                                }
                                for point in values
                            ],
                            x="Timestamp",
                            y=metric_labels[key],
                            height=210,
                        )
                    else:
                        st.metric(metric_labels[key], f"{values[-1]['Value']:g}")
                        if len(values) > 1:
                            st.caption(
                                "Saved readings share a timestamp; no "
                                "distinct-time trend is available yet."
                            )
                        else:
                            st.caption(
                                "Only one saved reading; no trend available."
                            )
            if not trend_drawn:
                st.caption(
                    "Historical trends are not available yet. These panels "
                    "show available saved readings without inventing timestamps."
                )
        else:
            if summary["sensor_report_count"]:
                st.markdown(
                    '<div class="empty-state">Sensor reports are saved, but they contain no finite numeric values for these metrics. Review the original readings in Maintenance History.</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    '<div class="empty-state">No sensor readings have been saved yet. Include optional readings when reporting an issue to begin building this monitoring view.</div>',
                    unsafe_allow_html=True,
                )

    equipment_column, orders_column = st.columns([1, 1], gap="medium")
    with equipment_column, st.container(key="dashboard-equipment-panel"):
        st.markdown(
            '<div class="dashboard-panel-title">Equipment Status</div><div class="dashboard-panel-caption">Status reflects the latest stored report and deterministic demo rules, not a verified safety diagnosis.</div>',
            unsafe_allow_html=True,
        )
        if summary["equipment_health"]:
            for item, (state, state_class, explanation) in zip(
                summary["equipment_health"], health_states
            ):
                st.markdown(
                    f"""
                    <div class="equipment-item">
                        <div class="equipment-item-header">
                            <div>
                                <div class="equipment-name">{escape(str(item["equipment_id"]))}</div>
                                <div class="activity-meta">{escape(str(item["equipment_type"]))}</div>
                            </div>
                            <span class="activity-status {state_class}">{escape(state)}</span>
                        </div>
                        <div class="activity-meta">{escape(explanation)} · {int(item["issue_count"] or 0)} reported issue(s)</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div class="empty-state">No equipment has been registered yet. Report an issue to register equipment and capture its first readings.</div>',
                unsafe_allow_html=True,
            )

    with orders_column, st.container(key="dashboard-orders-panel"):
        st.markdown(
            '<div class="dashboard-panel-title">Upcoming Maintenance / Work Orders</div><div class="dashboard-panel-caption">Drafts awaiting technician review · no scheduling dates are stored</div>',
            unsafe_allow_html=True,
        )
        if summary["work_orders"]:
            for order in summary["work_orders"]:
                draft = json.loads(order["draft_json"] or "{}")
                priority = str(draft.get("priority", "requires_review"))
                status_class = {
                    "draft": "status-warning",
                    "approved": "status-success",
                    "rejected": "status-critical",
                    "completed": "status-success",
                }.get(order["status"], "status-unknown")
                status_label = work_order_status_label(order["status"])
                technician = order["reviewed_by"] or "Awaiting technician review"
                st.markdown(
                    f"""
                    <div class="work-order-row">
                        <div class="equipment-item-header">
                            <strong>WO-{int(order["work_order_id"]):04d}</strong>
                            <span class="activity-status {status_class}">{escape(status_label)}</span>
                        </div>
                        <div class="work-order-summary">{escape(str(draft.get("summary") or order["description"]))}</div>
                        <div class="activity-meta">{escape(str(order["equipment_id"]))} · Issue #{int(order["issue_id"])} · {escape(str(technician))}</div>
                        <span class="priority-badge">Priority: {escape(priority.replace("_", " ").title())}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div class="empty-state">No work orders are awaiting technician review. Scheduling dates are not stored, so no upcoming appointments are shown.</div>',
                unsafe_allow_html=True,
            )
        if st.button("Open Work Orders", key="dashboard-open-work-orders"):
            if summary["work_orders"]:
                st.session_state["last_issue_id"] = summary["work_orders"][0]["issue_id"]
                st.session_state["work_orders_issue_id"] = summary["work_orders"][0]["issue_id"]
            st.session_state["current_page"] = "Work Orders"
            st.rerun()

    st.markdown(
        '<div class="dashboard-section-heading">Recent Activity</div>',
        unsafe_allow_html=True,
    )
    with st.container(key="dashboard-activity-panel"):
        if summary["recent_activity"]:
            for row in summary["recent_activity"]:
                event_type = str(row["event_type"]).replace("_", " ").title()
                status = str(row["status"] or "Issue recorded")
                status_class = {
                    "rejected": "status-critical",
                    "draft": "status-warning",
                    "approved": "status-success",
                    "completed": "status-success",
                }.get(status.lower(), "status-unknown")
                status = work_order_status_label(status)
                description = row["description"] or "Maintenance record updated"
                equipment_id = row["equipment_id"] or "Equipment not available"
                stamp = row["created_at"] or "Timestamp unavailable"
                st.markdown(
                    f"""
                    <div class="activity-item">
                        <div>
                            <div class="activity-title">{escape(str(description))}</div>
                            <div class="activity-meta">{escape(str(equipment_id))} · {escape(event_type)} · {escape(str(stamp))}</div>
                        </div>
                        <span class="activity-status {status_class}">{escape(status)}</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div class="empty-state">No maintenance activity is recorded yet.</div>',
                unsafe_allow_html=True,
            )


def render_issue_form_page():
    st.markdown(
        """
        <div class="page-header">
            <h1>Report an issue</h1>
            <p>Capture the equipment state and supporting evidence for technician review.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("issue_form"):
        equipment_type = st.selectbox(
            "Equipment type",
            ["Centrifugal Pump", "Motor", "Compressor", "Other"],
        )
        equipment_id = st.text_input("Equipment identifier", "CP-101")
        description = st.text_area(
            "Issue description",
            placeholder="Describe the observed problem...",
        )
        events_text = st.text_area(
            "Recent operating events",
            placeholder="Enter one event per line...",
        )

        with st.container(key="sensor-section"):
            st.markdown(
                '<div class="sensor-section-title">Optional sensor readings</div>',
                unsafe_allow_html=True,
            )
            col1, col2, col3 = st.columns(3)
            with col1:
                vibration = st.text_input("Vibration (mm/s)")
            with col2:
                temperature = st.text_input("Bearing temperature (°C)")
            with col3:
                pressure = st.text_input("Discharge pressure (bar)")

        with st.container(key="issue-submit-row"):
            submitted = st.form_submit_button("Analyze issue", type="primary")

    if submitted:
        if not equipment_id.strip() or not description.strip():
            st.error("Equipment identifier and issue description are required.")
            return

        try:
            readings = {}
            for key, raw in [
                ("vibration_mm_s", vibration),
                ("bearing_temperature_c", temperature),
                ("discharge_pressure_bar", pressure),
            ]:
                if raw and raw.strip():
                    try:
                        numeric_reading = float(raw)
                        readings[key] = (
                            numeric_reading
                            if math.isfinite(numeric_reading)
                            else raw.strip()
                        )
                    except ValueError:
                        readings[key] = raw

            sensor_results = evaluate_sensor_readings(readings)

            with st.spinner("Saving the issue and retrieving relevant manual evidence..."):
                register_equipment(equipment_id, equipment_type)
                issue = {
                    "equipment_id": equipment_id.strip(),
                    "equipment_type": equipment_type,
                    "description": description.strip(),
                    "operating_events": [
                        line.strip()
                        for line in events_text.splitlines()
                        if line.strip()
                    ],
                    "sensor_readings": readings,
                }

                issue_id = create_issue(
                    equipment_id=equipment_id,
                    description=description,
                    operating_events=issue["operating_events"],
                    sensor_readings=readings,
                    observations=[{"text": description.strip(), "citations": []}],
                )

                evidence = search_manuals(
                    f"{equipment_type} {description} " + " ".join(issue["operating_events"]),
                    top_k=3,
                )

            st.session_state["last_issue_id"] = issue_id
            st.session_state["work_orders_issue_id"] = issue_id
            st.session_state["last_sensor_results"] = sensor_results
            st.session_state["last_evidence"] = evidence
            st.session_state["last_issue"] = issue
            st.session_state.pop("last_analysis", None)
            st.session_state.pop("last_analysis_issue_id", None)

            render_sensor_results(sensor_results)

            if not evidence and AI_PROVIDER != "demo":
                st.warning("No relevant manual sections were found. The issue was saved, but AI analysis was not generated.")
                st.info("Saved issue records remain available in Maintenance History.")
                return

            spinner_message = (
                "Preparing deterministic demo guidance..."
                if AI_PROVIDER == "demo"
                else "Analyzing the issue with the configured AI provider..."
            )
            with st.spinner(spinner_message):
                analysis = analyze_issue(issue, sensor_results, evidence)

            st.session_state["last_analysis"] = analysis
            st.session_state["last_analysis_issue_id"] = issue_id
            completion = (
                "demo guidance prepared"
                if analysis.get("ai_provider") == "demo"
                else "analyzed successfully"
            )
            st.success(f"Issue #{issue_id} was saved and {completion}.")

        except (ValueError, AIServiceError) as exc:
            report_issue_workflow_error(
                exc,
                AI_PROVIDER,
                (
                    equipment_id,
                    equipment_type,
                    description,
                    events_text,
                    vibration,
                    temperature,
                    pressure,
                    OPENAI_API_KEY,
                ),
                st.error,
            )
        except Exception as exc:
            report_issue_workflow_error(
                exc,
                AI_PROVIDER,
                (
                    equipment_id,
                    equipment_type,
                    description,
                    events_text,
                    vibration,
                    temperature,
                    pressure,
                    OPENAI_API_KEY,
                ),
                lambda _message: st.error(
                    "The report workflow failed unexpectedly. "
                    "Check the application logs and try again."
                ),
            )


def render_work_orders_page():
    st.markdown(
        """
        <div class="page-header">
            <h1>Work orders</h1>
            <p>Review and maintain work orders with technician approval or rejection. Approval applies to maintenance work only and does not authorize equipment operation.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    try:
        issue_options = get_issue_options()
    except Exception:
        logger.exception("Could not load saved issue options for work orders")
        st.error("Saved issues could not be loaded. Check the application logs and try again.")
        return
    if not issue_options:
        st.info("No saved issues are available. Report an issue before creating a work order.")
        return

    issue_ids = [int(item["issue_id"]) for item in issue_options]
    preferred_issue_id = st.session_state.get(
        "work_orders_issue_id",
        st.session_state.get("last_issue_id"),
    )
    if preferred_issue_id not in issue_ids:
        preferred_issue_id = issue_ids[0]
    if "work_orders_issue_id" not in st.session_state:
        st.session_state["work_orders_issue_id"] = preferred_issue_id

    issue_descriptions = {
        int(item["issue_id"]): str(item["description"])
        for item in issue_options
    }
    issue_id = st.selectbox(
        "Select saved issue",
        issue_ids,
        format_func=lambda value: (
            f"Issue #{value} — {issue_descriptions[value][:70]}"
        ),
        key="work_orders_issue_id",
    )
    issue_id = int(issue_id)
    st.session_state["last_issue_id"] = issue_id

    try:
        orders = get_work_orders(int(issue_id))
    except Exception:
        logger.exception("Could not load work orders for issue %s", issue_id)
        st.error("Work orders could not be loaded. Check the application logs and try again.")
        return
    if not orders:
        try:
            issue = get_issue(int(issue_id))
        except Exception:
            logger.exception("Could not load saved issue %s", issue_id)
            st.error("The saved issue could not be loaded. Check the application logs and try again.")
            return

        if issue is None:
            st.warning(f"Issue #{int(issue_id)} was not found. Select a saved issue ID.")
            return

        st.caption(
            "Create a technician-review draft from this saved issue. "
            "The draft will be linked to this issue and will not be approved."
        )
        if st.button(
            "Create Work Order Draft",
            type="primary",
            key=f"create-work-order-{int(issue_id)}",
        ):
            try:
                if (
                    st.session_state.get("last_issue_id") == int(issue_id)
                    and st.session_state.get("last_analysis_issue_id")
                    == int(issue_id)
                    and isinstance(st.session_state.get("last_analysis"), dict)
                ):
                    draft = draft_from_analysis(
                        st.session_state["last_analysis"]
                    )
                else:
                    draft = draft_from_issue(issue)

                work_order_id, created = create_work_order_once(
                    int(issue_id),
                    draft,
                )
            except ValueError as exc:
                st.error(str(exc))
                return
            except Exception:
                logger.exception(
                    "Could not create work-order draft for issue %s",
                    issue_id,
                )
                st.error(
                    "The work-order draft could not be saved. The issue remains "
                    "available; check the application logs and try again."
                )
                return

            if created:
                st.success(
                    f"Work order #{work_order_id} was saved with Pending "
                    "Review status. It has not been approved."
                )
            else:
                st.info(
                    f"Work order #{work_order_id} already exists for this "
                    "issue; no duplicate was created."
                )
            try:
                orders = get_work_orders(int(issue_id))
            except Exception:
                logger.exception(
                    "Could not reload work orders for issue %s",
                    issue_id,
                )
                st.error(
                    "The draft was saved, but the work-order list could not be "
                    "refreshed. Reopen this issue's Work Orders page."
                )
                return

    if not orders:
        st.info("No work order exists for this saved issue yet.")

    for order in orders:
        draft = order.get("draft", {})
        with st.expander(f"Work order #{order['work_order_id']}"):
            st.markdown(status_badge(order["status"]), unsafe_allow_html=True)
            if order["status"] == "approved":
                st.info(
                    "This maintenance approval does not establish equipment-"
                    "operation safety or authorize equipment operation."
                )
            elif order["status"] == "rejected":
                st.warning("Rejected; this work order is not approved for maintenance work.")
            st.markdown(priority_badge(draft.get("priority", "requires_review")), unsafe_allow_html=True)
            st.write(draft.get("summary", ""))
            st.write("Created:", order.get("created_at"))
            st.write("Reviewed by:", order.get("reviewed_by") or "Not reviewed")
            if draft.get("actions"):
                for action in draft["actions"]:
                    st.write(f"• {action}")
            if order.get("technician_notes"):
                st.write("Technician notes:", order["technician_notes"])

            if order["status"] == "draft":
                with st.form(f"review_{order['work_order_id']}"):
                    reviewer = st.text_input("Technician name")
                    notes = st.text_area("Review notes")
                    decision = st.radio("Decision", ["Approve", "Reject"], horizontal=True)
                    confirm = st.checkbox("I reviewed the draft and supporting evidence.")
                    review_button = st.form_submit_button("Record decision")

                if review_button:
                    if not reviewer.strip():
                        st.error("Technician name is required.")
                    elif not confirm:
                        st.error("Please confirm the draft was reviewed.")
                    else:
                        try:
                            decision_value = "approved" if decision == "Approve" else "rejected"
                            review_work_order(order["work_order_id"], decision_value, reviewer, notes)
                            st.success(f"Work order #{order['work_order_id']} was {decision_value}.")
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
                        except Exception:
                            logger.exception(
                                "Could not record decision for work order %s",
                                order["work_order_id"],
                            )
                            st.error(
                                "The work-order decision could not be saved. "
                                "Check the application logs and try again."
                            )

                with st.form(f"edit_{order['work_order_id']}"):
                    tech_name = st.text_input("Editing technician", key=f"tech_{order['work_order_id']}")
                    summary_input = st.text_input(
                        "Summary",
                        value=draft.get("summary", ""),
                        key=f"summary_{order['work_order_id']}",
                    )
                    priority_input = st.selectbox(
                        "Priority",
                        ["requires_review", "routine", "medium", "high", "urgent"],
                        index=["requires_review", "routine", "medium", "high", "urgent"].index(draft.get("priority", "requires_review")),
                        key=f"priority_{order['work_order_id']}",
                    )
                    actions_input = st.text_area(
                        "Actions, one per line",
                        value="\n".join(draft.get("actions", [])),
                        key=f"actions_{order['work_order_id']}",
                    )
                    save_draft = st.form_submit_button("Save draft changes")

                if save_draft:
                    if not tech_name.strip() or not summary_input.strip():
                        st.error("Technician name and summary are required to save a draft.")
                    else:
                        try:
                            update_work_order_draft(
                                order["work_order_id"],
                                {
                                    "summary": summary_input.strip(),
                                    "priority": priority_input,
                                    "actions": [
                                        line.strip()
                                        for line in actions_input.splitlines()
                                        if line.strip()
                                    ],
                                    "evidence_citations": draft.get("evidence_citations", []),
                                },
                                tech_name.strip(),
                            )
                            st.success(f"Draft work order #{order['work_order_id']} was updated.")
                            st.rerun()
                        except ValueError as exc:
                            st.error(str(exc))
                        except Exception:
                            logger.exception(
                                "Could not save draft work order %s",
                                order["work_order_id"],
                            )
                            st.error(
                                "Draft changes could not be saved. Check the "
                                "application logs and try again."
                            )


def render_history_page():
    st.markdown(
        """
        <div class="page-header">
            <h1>Maintenance history</h1>
            <p>Chronological issue records and equipment status changes.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    equipment_id = st.text_input("Equipment identifier", "CP-101")
    if st.button("Load history"):
        try:
            history = get_issue_history(equipment_id.strip())
        except Exception:
            logger.exception(
                "Could not load maintenance history for equipment %s",
                equipment_id.strip(),
            )
            st.error("Maintenance history could not be loaded. Check the application logs and try again.")
            return
        if not history:
            st.info("No reports were found for this equipment identifier.")
            return

        for item in history:
            with st.expander(f"Issue #{item['issue_id']} · {item['created_at']}"):
                st.write("Description:", item["description"])
                st.write("Operating events:", item["operating_events"])
                st.write("Sensor readings:", item["sensor_readings"])
                st.write("Observations:", item["observations"])
                st.write("Possible causes:", item["possible_causes"])
                st.write("Confirmed findings:", item["confirmed_findings"])


with st.sidebar:
    st.markdown(
        """
        <div class="brand-box">
            <h1>MaintainAI</h1>
            <p>Industrial Intelligence</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="sidebar-section">Navigation</div>', unsafe_allow_html=True)
    page_labels = {
        "Dashboard": "🏭 Dashboard",
        "Report an Issue": "🛠️ Report an Issue",
        "Analysis Results": "📊 Analysis Results",
        "Work Orders": "📦 Work Orders",
        "Maintenance History": "🕘 Maintenance History",
    }
    current_page = st.session_state.get("current_page", "Dashboard")
    choices = list(page_labels.values())
    selected_label = page_labels.get(current_page, page_labels["Dashboard"])
    selected = st.radio(
        "Main navigation",
        choices,
        index=choices.index(selected_label),
        label_visibility="collapsed",
    )
    st.session_state["current_page"] = next(
        key for key, value in page_labels.items() if value == selected
    )
    st.markdown("---")
    st.caption("Maintenance Intelligence Platform")
    st.caption("AI provider: configurable")
    st.caption("Sensor thresholds: illustrative only")


page = st.session_state.get("current_page", "Dashboard")
if page == "Dashboard":
    render_dashboard_page()
elif page == "Report an Issue":
    render_issue_form_page()
elif page == "Analysis Results":
    render_analysis_results_page()
elif page == "Work Orders":
    render_work_orders_page()
else:
    render_history_page()
