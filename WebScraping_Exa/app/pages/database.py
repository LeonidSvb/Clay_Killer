"""
app/pages/database.py — Database management page.

Sections:
  1. Connection status
  2. Import CSV into leads_master + workspace_leads
  3. Workspaces list
  4. Stats
"""

import os
import pandas as pd
import streamlit as st

from core.db import (
    is_connected,
    get_workspaces,
    get_leads_master_count,
    workspace_exists,
    import_csv_to_db,
    delete_workspace,
)


def render():
    st.title("Database")

    _render_connection()
    st.divider()
    _render_import()
    st.divider()
    _render_workspaces()
    st.divider()
    _render_stats()


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _render_connection():
    st.subheader("Connection")
    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        st.warning("DATABASE_URL not set. Go to Settings and add it to .env")
        return

    if is_connected():
        masked = db_url[:20] + "..." if len(db_url) > 20 else db_url
        st.success(f"Connected — {masked}")
    else:
        st.error("Cannot connect. Check DATABASE_URL in Settings.")


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def _render_import():
    st.subheader("Import CSV")

    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        st.info("Set DATABASE_URL in Settings to enable import.")
        return

    source = st.radio(
        "Source",
        ["Upload file", "Choose from working folder"],
        horizontal=True,
        label_visibility="collapsed",
    )

    df = None
    file_name = None

    if source == "Upload file":
        uploaded = st.file_uploader("CSV file", type=["csv"], label_visibility="collapsed")
        if uploaded:
            df = _read_csv(uploaded)
            file_name = uploaded.name

    else:
        working_folder = os.getenv("WORKING_FOLDER", "").strip()
        if not working_folder or not os.path.isdir(working_folder):
            st.warning("WORKING_FOLDER not set or not found.")
        else:
            csv_files = [
                f for f in os.listdir(working_folder)
                if f.lower().endswith(".csv")
            ]
            if not csv_files:
                st.info("No CSV files in working folder.")
            else:
                selected = st.selectbox("Select file", csv_files)
                if selected:
                    path = os.path.join(working_folder, selected)
                    df = _read_csv(path)
                    file_name = selected

    if df is None or file_name is None:
        return

    # Preview
    st.caption(f"{len(df)} rows, {len(df.columns)} columns")
    st.dataframe(df.head(5), use_container_width=True)

    # Workspace name
    default_name = os.path.splitext(file_name)[0]
    workspace_name = st.text_input("Workspace name", value=default_name)

    # Duplicate warning
    existing_ws = workspace_exists(file_name)
    if existing_ws:
        st.warning(
            f"File '{file_name}' was already imported as workspace "
            f"**{existing_ws['name']}** (#{existing_ws['id']}, "
            f"{existing_ws['created_at'].strftime('%Y-%m-%d %H:%M')}). "
            "You can still import — duplicates will be skipped."
        )

    if st.button("Import to Database", type="primary"):
        if not workspace_name.strip():
            st.error("Workspace name cannot be empty.")
            return
        rows = df.to_dict(orient="records")
        with st.spinner(f"Importing {len(rows)} rows..."):
            try:
                result = import_csv_to_db(rows, workspace_name.strip(), file_name)
                st.success(
                    f"Done. Workspace #{result['workspace_id']} created. "
                    f"Added: {result['added']} | Already existed: {result['existing']} | "
                    f"Errors: {result['errors']}"
                )
                st.rerun()
            except Exception as e:
                st.error(f"Import failed: {e}")


def _read_csv(source) -> pd.DataFrame:
    try:
        return pd.read_csv(source, dtype=str, keep_default_na=False)
    except Exception as e:
        st.error(f"Cannot read CSV: {e}")
        return None


# ---------------------------------------------------------------------------
# Workspaces list
# ---------------------------------------------------------------------------

def _render_workspaces():
    st.subheader("Workspaces")

    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        return

    workspaces = get_workspaces()
    if not workspaces:
        st.info("No workspaces yet. Import a CSV to create one.")
        return

    for ws in workspaces:
        col1, col2 = st.columns([5, 1])
        with col1:
            created = ws["created_at"].strftime("%Y-%m-%d %H:%M")
            rows_label = f"{ws['total_rows']} rows" if ws["total_rows"] else "? rows"
            st.markdown(
                f"**{ws['name']}** &nbsp; `#{ws['id']}` &nbsp; "
                f"{rows_label} &nbsp; {created}"
            )
            if ws["file_name"]:
                st.caption(ws["file_name"])
        with col2:
            if st.button("Delete", key=f"del_ws_{ws['id']}"):
                st.session_state[f"confirm_del_{ws['id']}"] = True

        if st.session_state.get(f"confirm_del_{ws['id']}"):
            st.warning(
                f"Delete workspace **{ws['name']}**? "
                "This removes workspace_leads but keeps leads_master intact."
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Yes, delete", key=f"yes_del_{ws['id']}", type="primary"):
                    delete_workspace(ws["id"])
                    del st.session_state[f"confirm_del_{ws['id']}"]
                    st.rerun()
            with c2:
                if st.button("Cancel", key=f"cancel_del_{ws['id']}"):
                    del st.session_state[f"confirm_del_{ws['id']}"]
                    st.rerun()


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def _render_stats():
    st.subheader("Stats")

    db_url = os.getenv("DATABASE_URL", "").strip()
    if not db_url:
        return

    col1, col2 = st.columns(2)
    with col1:
        total = get_leads_master_count()
        st.metric("Unique leads (master)", f"{total:,}")
    with col2:
        workspaces = get_workspaces()
        st.metric("Workspaces", len(workspaces))
