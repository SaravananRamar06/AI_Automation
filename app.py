"""AttendGuard: AI-powered attendance & performance risk automation."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from core import ai, notify, risk, summary
from core import timetable as tt
from core.config import THRESHOLD, secret

st.set_page_config(page_title="AttendGuard", page_icon="🎓", layout="wide")
SAMPLE = Path(__file__).parent / "data" / "sample"
STATUS_COLORS = {"CRITICAL": "#d62728", "WARNING": "#ff9f1c", "SAFE": "#2ca02c"}
ss = st.session_state

st.markdown("""
<style>
.block-container {padding-top: 2rem; max-width: 1300px;}
h1, h2, h3 {letter-spacing: -0.02em;}
[data-testid="stMetric"] {background: #fff; border: 1px solid #E5E7EB; border-radius: 14px;
  padding: 14px 18px; box-shadow: 0 1px 2px rgba(16,24,40,.05);}
[data-testid="stMetricLabel"] {color: #6B7280; font-weight: 500;}
[data-testid="stSidebar"] {background: #111827;}
[data-testid="stSidebar"] * {color: #E5E7EB !important;}
[data-testid="stSidebar"] code {background: #1F2937; color: #A5B4FC !important;}
[data-testid="stPlotlyChart"], [data-testid="stDataFrame"] {background: #fff; border: 1px solid #E5E7EB;
  border-radius: 14px; padding: 6px;}
.stButton > button {border-radius: 10px; font-weight: 600;}
</style>
""", unsafe_allow_html=True)


def show_df(df, hide_index=False, column_config=None):
    """st.dataframe, falling back to plain HTML where pyarrow can't load (e.g. locked-down Windows)."""
    try:
        import pyarrow  # noqa: F401
        st.dataframe(df, hide_index=hide_index, column_config=column_config)
    except ImportError:
        st.markdown(df.to_html(index=not hide_index, border=0), unsafe_allow_html=True)


# ---------------- data loading ----------------

def run_analysis(att, marks, timetable):
    subj, students = risk.analyze(att, marks, timetable)
    ss.update(att=att, marks=marks, tt=timetable, subj=subj, students=students, drafts={})
    # Automatic: call every student who just fell below the threshold.
    ss.last_calls = notify.auto_call(students)


def load_sample():
    run_analysis(pd.read_csv(SAMPLE / "attendance.csv"), pd.read_csv(SAMPLE / "marks.csv"),
                 pd.read_csv(SAMPLE / "timetable.csv"))


if "students" not in ss and st.query_params.get("roll"):
    load_sample()  # booking links from emails open straight into the app with data ready

has_data = "students" in ss

# ---------------- sidebar ----------------

PAGES = ["📤 Upload", "📊 Dashboard", "🚨 At-Risk Students", "✉️ Notify", "📅 Book a Slot", "📞 Calls & Weekly Summary"]
default_page = 4 if st.query_params.get("roll") else 0
with st.sidebar:
    st.title("🎓 AttendGuard")
    st.caption(f"Attendance & performance risk automation · threshold {THRESHOLD:g}%")
    page = st.radio("Go to", PAGES, index=default_page, label_visibility="collapsed")
    st.divider()
    st.markdown("**Integrations**")
    st.markdown(f"🤖 AI: `{ai.engine_name()}`")
    st.markdown(f"✉️ Email: `{notify.email_mode()}`")
    st.markdown(f"📞 Calls: `{notify.call_mode()}`")
    if secret("DEMO_INBOX"):
        st.caption(f"Demo mode: emails redirected to {secret('DEMO_INBOX')}")


def need_data():
    st.info("No data yet. Go to **📤 Upload** and upload sheets or click **Load sample data**.")
    st.stop()


# ---------------- pages ----------------

if page == PAGES[0]:
    st.header("📤 Upload attendance, test results & timetables")
    c1, c2, c3 = st.columns(3)
    f_att = c1.file_uploader("Attendance sheet (CSV/XLSX)", type=["csv", "xlsx"])
    f_marks = c2.file_uploader("Recent test results (CSV/XLSX)", type=["csv", "xlsx"])
    f_tt = c3.file_uploader("Teachers' timetable (CSV/XLSX)", type=["csv", "xlsx"])
    b1, b2 = st.columns([1, 1])
    if b1.button("🚀 Analyze uploaded files", type="primary", disabled=f_att is None):
        try:
            run_analysis(risk.read_table(f_att), risk.read_table(f_marks) if f_marks else None,
                         risk.read_table(f_tt) if f_tt else pd.read_csv(SAMPLE / "timetable.csv"))
            st.success("Analysis complete.")
        except Exception as e:
            st.error(f"Could not process files: {e}")
    if b2.button("🧪 Load sample data (3 departments, 42 students)"):
        load_sample()
        st.success("Sample data loaded and analysed.")

    if "students" in ss:
        s = ss.students
        st.markdown(f"**{len(s)} students analysed** · 🔴 {int((s.status == 'CRITICAL').sum())} below {THRESHOLD:g}% · "
                    f"🟠 {int((s.status == 'WARNING').sum())} close · "
                    f"📉 {int(((s.weak_in != '') | (s.falling_in != '')).sum())} weak/falling marks")
        calls = ss.get("last_calls", [])
        if calls:
            st.warning(f"📞 Auto-call triggered for {len(calls)} student(s) below {THRESHOLD:g}% "
                       "(see **Calls & Weekly Summary**).")

    with st.expander("📄 Expected file formats & templates"):
        st.markdown(
            "- **Attendance**: `roll_no, name, email, phone, department, adviser_name, adviser_email, subject, classes_held, classes_attended`\n"
            "- **Test results**: `roll_no, subject, test1, test2, test3, …` (any number of test columns, oldest first)\n"
            "- **Timetable** (teaching periods): `teacher, teacher_email, department, subject, day (Mon-Fri), slot (e.g. 09:00-10:00)`")
        d1, d2, d3 = st.columns(3)
        for col, name in zip((d1, d2, d3), ("attendance.csv", "marks.csv", "timetable.csv")):
            col.download_button(f"⬇️ {name}", (SAMPLE / name).read_bytes(), file_name=name, mime="text/csv")

elif page == PAGES[1]:
    st.header("📊 Risk dashboard")
    if not has_data:
        need_data()
    s, subj = ss.students, ss.subj
    k = st.columns(5)
    k[0].metric("Students", len(s))
    k[1].metric(f"Below {THRESHOLD:g}%", int((s.status == "CRITICAL").sum()))
    k[2].metric("Close to limit", int((s.status == "WARNING").sum()))
    k[3].metric("Weak / falling marks", int(((s.weak_in != "") | (s.falling_in != "")).sum()))
    k[4].metric("Avg attendance", f"{s.overall_pct.mean():.1f}%")

    c1, c2 = st.columns(2)
    dept_status = s.groupby(["department", "status"]).size().reset_index(name="students")
    c1.plotly_chart(px.bar(dept_status, x="department", y="students", color="status",
                           color_discrete_map=STATUS_COLORS, title="Department-wise risk",
                           category_orders={"status": ["CRITICAL", "WARNING", "SAFE"]}))
    heat = subj.pivot_table(index="department", columns="subject", values="att_pct", aggfunc="mean")
    c2.plotly_chart(px.imshow(heat.round(1), text_auto=True, aspect="auto", color_continuous_scale="RdYlGn",
                              zmin=70, zmax=100, title="Subject-wise average attendance %"))

    subs = risk.subject_summary(subj)
    c3, c4 = st.columns(2)
    c3.plotly_chart(px.bar(subs.head(10), x="below_85", y="subject", color="department", orientation="h",
                           title=f"Subjects with most students below {THRESHOLD:g}%")
                    .update_layout(yaxis={"categoryorder": "total ascending"}))
    c4.plotly_chart(px.scatter(s, x="overall_pct", y="avg_mark", color="status", size="risk",
                               hover_data=["name", "roll_no", "department"], color_discrete_map=STATUS_COLORS,
                               title="Attendance vs latest marks (bubble = risk)"))

    st.subheader("🔥 Most at-risk students")
    show_df(s[s.at_risk][["roll_no", "name", "department", "overall_pct", "worst_pct", "max_need",
                               "below_85", "weak_in", "falling_in", "risk"]].head(15), hide_index=True,
                 column_config={"risk": st.column_config.ProgressColumn("risk", min_value=0, max_value=100, format="%d"),
                                "max_need": st.column_config.NumberColumn("classes needed in a row")})
    st.subheader("🏫 Department summary")
    show_df(risk.department_summary(s), hide_index=True)

elif page == PAGES[2]:
    st.header("🚨 At-risk students (most at-risk first)")
    if not has_data:
        need_data()
    s, subj = ss.students, ss.subj
    f1, f2, f3 = st.columns(3)
    depts = f1.multiselect("Department", sorted(s.department.unique()))
    statuses = f2.multiselect("Attendance status", ["CRITICAL", "WARNING", "SAFE"], default=["CRITICAL", "WARNING"])
    marks_only = f3.checkbox("Include students flagged only for weak/falling marks", value=True)
    view = s.copy()
    if depts:
        view = view[view.department.isin(depts)]
    mask = view.status.isin(statuses)
    if marks_only:
        mask |= (view.weak_in != "") | (view.falling_in != "")
    view = view[mask]
    show_df(view[["roll_no", "name", "department", "status", "overall_pct", "worst_pct", "below_85",
                       "max_need", "near_85", "weak_in", "falling_in", "risk"]], hide_index=True,
                 column_config={"risk": st.column_config.ProgressColumn("risk", min_value=0, max_value=100, format="%d"),
                                "max_need": st.column_config.NumberColumn("attend N in a row")})

    st.subheader("🔍 Student detail")
    if len(view):
        pick = st.selectbox("Student", view.roll_no + " · " + view.name)
        roll = pick.split(" · ")[0]
        rows = subj[subj.roll_no == roll]
        show_df(rows[["subject", "classes_held", "classes_attended", "att_pct", "status", "need_in_row",
                           "can_miss", "scores", "weak", "falling", "teacher"]], hide_index=True,
                     column_config={"need_in_row": "attend N in a row to reach 85%",
                                    "can_miss": "can still miss"})
        long = rows[["subject", "scores"]].copy()
        long = long[long.scores != ""]
        if len(long):
            pts = [{"subject": r.subject, "test": f"Test {i + 1}", "score": float(v)}
                   for r in long.itertuples() for i, v in enumerate(r.scores.split(" → "))]
            st.plotly_chart(px.line(pd.DataFrame(pts), x="test", y="score", color="subject", markers=True,
                                    title="Test score trend").add_hline(y=40, line_dash="dot",
                                                                         annotation_text="weak line"))

elif page == PAGES[3]:
    st.header("✉️ Personal warnings & faculty alerts")
    if not has_data:
        need_data()
    s, subj = ss.students, ss.subj
    targets = s[s.at_risk]
    app_url = secret("APP_URL").rstrip("/")
    st.write(f"**{len(targets)} at-risk students** will get a personal AI-written email. Subject teachers and "
             "faculty advisers get a digest of their at-risk students.")
    redirect = st.text_input("Demo inbox: redirect every email here (leave blank to send to real addresses)",
                             value=secret("DEMO_INBOX"))

    if st.button("✨ 1. Generate AI warning emails", type="primary"):
        def draft(row):
            stu = row.to_dict()
            rows = subj[subj.roll_no == stu["roll_no"]].to_dict("records")
            link = f"{app_url}/?roll={stu['roll_no']}" if app_url else ""
            return stu["roll_no"], ai.student_email(stu, rows, link)

        with st.spinner(f"Drafting {len(targets)} personalised emails…"):
            with ThreadPoolExecutor(max_workers=8) as pool:
                ss.drafts = dict(pool.map(draft, [r for _, r in targets.iterrows()]))
        engines = pd.Series([d[2] for d in ss.drafts.values()]).value_counts().to_dict()
        st.success(f"Drafted {len(ss.drafts)} emails · engines used: {engines}")

    drafts = ss.get("drafts", {})
    if drafts:
        pick = st.selectbox("Preview", [f"{r} · {s.set_index('roll_no').loc[r, 'name']}" for r in drafts])
        roll = pick.split(" · ")[0]
        subj_line, body, engine = drafts[roll]
        st.caption(f"Written by: {engine}")
        new_body = st.text_area("Email body (editable)", body, height=280)
        drafts[roll] = (subj_line, new_body, engine)

        # Teacher + adviser digests
        risky = subj[subj.at_risk]
        digests = []
        for (teacher, email), grp in risky.groupby(["teacher", "teacher_email"]):
            if not email:
                continue
            lines = [f"- {r.name} ({r.roll_no}), {r.subject}: attendance {r.att_pct}% [{r.status}]"
                     + (f", needs {r.need_in_row} classes in a row" if r.need_in_row else "")
                     + (f", scores {r.scores}" if r.weak or r.falling else "") for r in grp.itertuples()]
            digests.append({"to": email, "kind": "teacher", "subject": f"AttendGuard: {len(grp)} at-risk students in your subjects",
                            "body": f"Dear {teacher},\n\nThe following students need your attention:\n\n" + "\n".join(lines)
                            + "\n\nThey have been asked to book a slot during your free periods.\n\nAttendGuard"})
        for (adviser, email), grp in targets.groupby(["adviser_name", "adviser_email"]):
            if not email:
                continue
            lines = [f"- {r.name} ({r.roll_no}): overall {r.overall_pct}%, risk {r.risk:g}"
                     + (f", below 85 in {r.below_85}" if r.below_85 else "")
                     + (f", weak in {r.weak_in}" if r.weak_in else "")
                     + (f", falling in {r.falling_in}" if r.falling_in else "") for r in grp.itertuples()]
            digests.append({"to": email, "kind": "adviser", "subject": f"AttendGuard: {len(grp)} of your advisees are at risk",
                            "body": f"Dear {adviser},\n\nAt-risk advisees (most at-risk first):\n\n" + "\n".join(lines)
                            + "\n\nEach student has received a personal warning email.\n\nAttendGuard"})
        with st.expander(f"👩‍🏫 {len(digests)} teacher/adviser digests"):
            for d in digests:
                st.markdown(f"**{d['kind'].title()} → {d['to']}**: {d['subject']}")
                st.text(d["body"])

        if st.button(f"📨 2. Send {len(drafts)} student emails + {len(digests)} faculty alerts"):
            msgs = [{"to": s.set_index("roll_no").loc[r, "email"], "kind": "student", "subject": d[0], "body": d[1]}
                    for r, d in drafts.items()] + digests
            with st.spinner("Sending…"):
                res = notify.send_emails(msgs, redirect_to=redirect.strip())
            st.success(f"Processed {len(res)} emails.")
            show_df(pd.DataFrame(res)[["kind", "to", "delivered_to", "subject", "status"]], hide_index=True)

elif page == PAGES[4]:
    st.header("📅 Book a slot with your subject teacher")
    if not has_data:
        need_data()
    s, subj = ss.students, ss.subj
    options = list(s.roll_no + " · " + s.name)
    qroll = st.query_params.get("roll")
    idx = next((i for i, o in enumerate(options) if o.split(" · ")[0] == qroll), 0)
    pick = st.selectbox("I am", options, index=idx)
    roll = pick.split(" · ")[0]
    stu = s.set_index("roll_no").loc[roll].to_dict() | {"roll_no": roll}
    rows = subj[subj.roll_no == roll].sort_values("att_pct")
    flagged = rows[rows.at_risk]
    st.caption(f"Overall attendance {stu['overall_pct']}% · status {stu['status']}")
    subject_opts = list(flagged.subject) or list(rows.subject)
    subject = st.selectbox("Subject (at-risk subjects listed first)",
                           subject_opts + [x for x in rows.subject if x not in subject_opts])
    r = rows[rows.subject == subject].iloc[0]
    if not r.teacher:
        st.warning("No timetable found for this subject's teacher.")
        st.stop()
    st.markdown(f"**Teacher:** {r.teacher} · attendance {r.att_pct}% · "
                + (f"attend next **{r.need_in_row}** in a row" if r.need_in_row else f"can miss {r.can_miss}"))
    with st.expander(f"🗓️ {r.teacher}'s weekly timetable (synced from upload)"):
        show_df(tt.week_grid(ss.tt, r.teacher))
    slots = tt.free_slots(ss.tt, r.teacher)
    if not slots:
        st.warning("No free slots in the next 7 days.")
        st.stop()
    choice = st.selectbox("Free slots (next 7 days)", [x["label"] for x in slots])
    note = st.text_input("What do you need help with?", f"Recovering attendance / marks in {subject}")
    if st.button("✅ Book appointment", type="primary"):
        slot = next(x for x in slots if x["label"] == choice)
        b = tt.book(stu, {"teacher": r.teacher, "teacher_email": r.teacher_email}, slot, subject, note)
        ics = tt.make_ics(b)
        body = (f"Appointment booked via AttendGuard\n\nStudent: {b['student']} ({b['roll_no']})\nTeacher: {b['teacher']}\n"
                f"Subject: {subject}\nWhen: {slot['label']}\nNote: {note}\n\nCalendar invite attached.")
        notify.send_emails([
            {"to": r.teacher_email, "kind": "booking", "subject": f"Appointment: {b['student']} · {slot['label']}", "body": body, "ics": ics},
            {"to": stu["email"], "kind": "booking", "subject": f"Confirmed: meeting with {r.teacher} · {slot['label']}", "body": body, "ics": ics},
        ])
        st.success(f"Booked {slot['label']} with {r.teacher}. Confirmation + calendar invite sent to both.")
        st.download_button("⬇️ Add to calendar (.ics)", ics, file_name="appointment.ics", mime="text/calendar")
    if tt.BOOKINGS:
        st.subheader("All bookings")
        show_df(pd.DataFrame(tt.BOOKINGS), hide_index=True)

elif page == PAGES[5]:
    st.header("📞 Automatic calls & 🗓️ weekly summary")
    if not has_data:
        need_data()
    st.markdown(f"Calls fire **automatically** whenever data is analysed and a student is below {THRESHOLD:g}% "
                f"in any subject (once per student). Mode: `{notify.call_mode()}`")
    c1, c2 = st.columns(2)
    if c1.button("🔁 Re-check now"):
        new = notify.auto_call(ss.students)
        st.info(f"{len(new)} new call(s) placed.")
    if c2.button("♻️ Reset call memory (demo)"):
        notify.CALLED.clear()
        st.info("Call memory cleared. Next analysis will call again.")
    if notify.CALL_LOG:
        show_df(pd.DataFrame(notify.CALL_LOG)[["time", "roll_no", "name", "dialled", "status", "message"]].iloc[::-1],
                     hide_index=True)

    st.divider()
    st.subheader("🗓️ Weekly summary")
    st.markdown("Sent **automatically every Monday 09:00 IST** by a GitHub Actions cron job "
                "(`.github/workflows/weekly-summary.yml`). You can also preview or send it now.")
    if st.button("👀 Preview weekly summary"):
        with st.spinner("Writing summary…"):
            ss.summary = summary.build(ss.subj, ss.students)
    if "summary" in ss:
        subj_line, body, engine = ss.summary
        st.caption(f"Insights written by: {engine}")
        st.text_area(subj_line, body, height=380)
        to = st.text_input("Send to", secret("SUMMARY_TO") or secret("DEMO_INBOX"))
        if st.button("📨 Send summary now") and to:
            res = notify.send_emails([{"to": to, "kind": "summary", "subject": subj_line, "body": body}], redirect_to="")
            st.success(f"Summary: {res[0]['status']}")

    if notify.EMAIL_LOG:
        with st.expander(f"📬 Email log / outbox ({len(notify.EMAIL_LOG)})"):
            show_df(pd.DataFrame(notify.EMAIL_LOG)[["time", "kind", "to", "delivered_to", "subject", "status"]].iloc[::-1],
                         hide_index=True)
