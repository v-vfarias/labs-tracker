from __future__ import annotations

import pandas as pd
import streamlit as st

from labs_tracker.config import load_settings
from labs_tracker.db import ensure_indexes, get_database
from labs_tracker.tasks import generate_tasks


@st.cache_data(ttl=60)
def load_data():
    db = get_database(load_settings())
    ensure_indexes(db)
    repos = [{k: v for k, v in doc.items() if k != "_id"} for doc in db.repos.find({})]
    items = [{k: v for k, v in doc.items() if k != "_id"} for doc in db.items.find({})]
    tasks = generate_tasks(db)
    return pd.DataFrame(repos), pd.DataFrame(items), pd.DataFrame(tasks)


def apply_filters(items: pd.DataFrame) -> pd.DataFrame:
    filtered = items.copy()
    with st.sidebar:
        st.header("Filters")
        for label, column in [
            ("Repo", "repoId"),
            ("Kind", "kind"),
            ("Status", "status"),
            ("Type", "typeOfIssue"),
            ("Test result", "testResult"),
        ]:
            if column in filtered and not filtered.empty:
                options = sorted(value for value in filtered[column].dropna().unique())
                selected = st.multiselect(label, options)
                if selected:
                    filtered = filtered[filtered[column].isin(selected)]
    return filtered


st.set_page_config(page_title="Labs Tracker", layout="wide")
st.title("Labs Tracker")
st.caption("Local issue and PR validation tracker. GitHub metadata is synced; manual validation fields are preserved.")

repos_df, items_df, tasks_df = load_data()
if repos_df.empty and items_df.empty:
    st.info("No synced data yet. Run `python -m labs_tracker.cli sync` after configuring .env and MongoDB.")

filtered_items = apply_filters(items_df) if not items_df.empty else items_df

view = st.sidebar.radio(
    "View",
    [
        "Repo health overview",
        "Issue breakdown",
        "PR validation queue",
        "Tasks of the day",
        "Recently closed/resolved items",
    ],
)

if view == "Repo health overview":
    st.subheader("Repo health overview")
    if not repos_df.empty:
        st.dataframe(repos_df[[c for c in ["id", "status", "lastUpdated", "lastTested", "products", "devs", "htmlUrl"] if c in repos_df]], use_container_width=True)
    st.metric("Tracked repos", len(repos_df))
    st.metric("Synced items", len(items_df))

elif view == "Issue breakdown":
    st.subheader("Issue breakdown")
    issues = filtered_items[filtered_items.get("kind", pd.Series(dtype=str)) == "issue"] if not filtered_items.empty else filtered_items
    cols = st.columns(4)
    for col, field in zip(cols, ["typeOfIssue", "resolution", "status", "testResult"]):
        with col:
            st.write(field)
            if not issues.empty and field in issues:
                st.bar_chart(issues[field].fillna("Unknown").value_counts())
    st.dataframe(issues, use_container_width=True)

elif view == "PR validation queue":
    st.subheader("PR validation queue")
    prs = filtered_items[filtered_items.get("kind", pd.Series(dtype=str)) == "pr"] if not filtered_items.empty else filtered_items
    if not prs.empty:
        prs = prs[(prs.get("state", pd.Series(dtype=str)) == "open") & (prs.get("draft", pd.Series(False, index=prs.index)) != True)]
        if "testResult" in prs:
            prs = prs[prs["testResult"] == "Not tested"]
    st.dataframe(prs, use_container_width=True)

elif view == "Tasks of the day":
    st.subheader("Tasks of the day")
    st.dataframe(tasks_df, use_container_width=True)

elif view == "Recently closed/resolved items":
    st.subheader("Recently closed/resolved items")
    closed = filtered_items[filtered_items.get("state", pd.Series(dtype=str)) == "closed"] if not filtered_items.empty else filtered_items
    if not closed.empty and "closedAt" in closed:
        closed = closed.sort_values("closedAt", ascending=False)
    st.dataframe(closed, use_container_width=True)
