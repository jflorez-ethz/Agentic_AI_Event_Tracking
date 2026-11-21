"""The control-room screen for the replay.

    streamlit run app.py

- Camera wall: every camera's frame at the current site time, refreshed each second.
- Clock controls (sidebar): play, pause, speed, jump, reset.
- Alert inbox: what the triage agent sent to a person, and what it closed itself.
- Review panel: the selected alert's clips, reason and agent steps, with approve/dismiss.
- Footage lookup: pick a camera and a time window and play it from the recorder,
  which is the same get_clip tool the agents use.

The agent never looks at this screen. It works only through fakecctv/tools.py.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import streamlit as st

from fakecctv.alerts import AlertStore
from fakecctv.clock import ReplayClock
from fakecctv.recorder import NotYetAvailable, Recorder
from fakecctv.site import load_site
from fakecctv.triage_stub import KIND_LABELS

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "runtime"
SPEEDS = [1, 2, 4, 8, 16, 60]

st.set_page_config(page_title="Control room (replay)", layout="wide")


@st.cache_resource
def setup():
    site = load_site(ROOT / "site" / "index.json")
    clock = ReplayClock(site.start, site.end, RUNTIME / "clock.json")
    recorder = Recorder(site, clock, RUNTIME / "clips")
    return site, clock, recorder


site, clock, recorder = setup()
store = AlertStore(RUNTIME)


def kind_label(kind: str) -> str:
    return KIND_LABELS.get(kind, kind.replace("_", " "))


# Sidebar: the replay clock ------------------------------------------------------
with st.sidebar:
    st.subheader(site.name)
    st.caption(f"Replay window {site.start:%a %d %b, %H:%M} to {site.end:%H:%M}")
    c1, c2 = st.columns(2)
    if c1.button("Play"):
        clock.play()
    if c2.button("Pause"):
        clock.pause()
    current = int(clock.speed) if int(clock.speed) in SPEEDS else 1
    speed = st.select_slider("Speed", options=SPEEDS, value=current, format_func=lambda s: f"{s}x")
    if speed != current:
        clock.set_speed(speed)
    with st.form("jump"):
        minutes = int(site.duration_s // 60)
        offset = st.number_input("Jump to minute", min_value=0, max_value=minutes, step=1,
                                 help=f"Minutes after {site.start:%H:%M}")
        if st.form_submit_button("Jump"):
            clock.jump(site.start + timedelta(minutes=int(offset)))
    if st.button("Back to the start"):
        clock.reset()
    st.caption("To clear the inbox as well, restart the runner with: python run_replay.py --reset")


# Camera wall ----------------------------------------------------------------------
@st.fragment(run_every=1.0)
def camera_wall():
    now = clock.now()
    state = "paused" if clock.paused else f"playing at {clock.speed:g}x"
    st.markdown(f"#### {now:%a %d %b %Y  %H:%M:%S}  ·  :gray[{state}]")
    alerting = {a["candidate"]["camera_id"] for a in store.all()
                if a["verdict"] == "escalate" and a["status"] == "pending"}
    cams = site.cameras
    for row in range(0, len(cams), 3):
        cols = st.columns(3)
        for col, cam in zip(cols, cams[row:row + 3]):
            with col:
                image = recorder.frame(cam.id, now)
                flag = "  :red[● alert]" if cam.id in alerting else ""
                if image is None:
                    st.info(f"{cam.id}: no recording")
                else:
                    st.image(image, width="stretch")
                st.markdown(f"**{cam.id}** · {cam.zone}{flag}")


# Alert inbox ----------------------------------------------------------------------
@st.fragment(run_every=2.0)
def alert_inbox():
    alerts = store.all()
    sent = [a for a in alerts if a["verdict"] == "escalate"]
    closed = [a for a in alerts if a["verdict"] != "escalate"]
    m1, m2, m3 = st.columns(3)
    m1.metric("Detector events", len(alerts))
    m2.metric("Sent to a person", len(sent))
    m3.metric("Closed by the agent", len(closed))

    if not alerts:
        st.caption("No events yet. Press Play and start the runner: python run_replay.py")
    for a in reversed(sent):
        c = a["candidate"]
        with st.container(border=True):
            colour = "red" if a["priority"] == "high" else "orange"
            st.markdown(f":{colour}[**{a['priority'].upper()}**] **{kind_label(c['kind'])}** · {c['camera_id']} "
                        f"{c['zone']} · {c['first_seen'][11:19]}  \n{a['reason']}")
            linked = [x for x in closed if x.get("linked_to") == a["id"]]
            if linked:
                st.caption("Also seen on " + ", ".join(x["candidate"]["camera_id"] for x in linked))
            left, right = st.columns([1, 2])
            if left.button("Review", key=f"open-{a['id']}"):
                st.session_state["selected"] = a["id"]
                st.rerun()
            right.markdown(f"Status: **{a['status']}**")

    if closed:
        with st.expander(f"Closed by the agent ({len(closed)})"):
            for a in reversed(closed):
                c = a["candidate"]
                st.markdown(f"- **{c['first_seen'][11:19]} {c['camera_id']}** {kind_label(c['kind'])}: {a['reason']}")
                if st.button("Review", key=f"open-{a['id']}"):
                    st.session_state["selected"] = a["id"]
                    st.rerun()


def review_panel():
    selected = st.session_state.get("selected")
    alert = next((a for a in store.all() if a["id"] == selected), None)
    if not alert:
        st.caption("Select Review on an alert to see its clips and the agent's steps.")
        return
    c = alert["candidate"]
    st.markdown(f"#### {alert['id']} · {kind_label(c['kind'])} · {c['camera_id']} {c['zone']}")
    st.markdown(f"**Agent verdict:** {alert['verdict']} ({alert['priority']}). {alert['reason']}")
    clips = alert.get("evidence", [])
    cols = st.columns(max(len(clips), 1))
    for col, path in zip(cols, clips):
        with col:
            if Path(path).exists():
                st.video(path)
                st.caption(Path(path).stem.replace("_", " "))
    if alert["verdict"] == "escalate" and alert["status"] == "pending":
        b1, b2, _ = st.columns([1, 1, 3])
        if b1.button("Approve alert", type="primary"):
            store.decide(alert["id"], "approved", clock.now())
            st.rerun()
        if b2.button("Dismiss"):
            store.decide(alert["id"], "dismissed by guard", clock.now())
            st.rerun()
    with st.expander("Agent steps (tool calls on the replay clock)"):
        for step in alert.get("trace", []):
            mark = "ok" if step["ok"] else "refused"
            st.markdown(f"`{step['site_time']}` **{step['tool']}** {step['args']} → {mark}")
            st.caption(str(step["result"])[:300])


# Footage lookup -------------------------------------------------------------------
def footage_lookup():
    st.caption("This uses the recorder's get_clip, the same tool the agents call. "
               "Anything after the replay clock is refused, because it has not been recorded yet.")
    def last_two_minutes():
        now = clock.now()
        st.session_state["lookup_from"] = f"{now - timedelta(minutes=2):%H:%M:%S}"
        st.session_state["lookup_to"] = f"{now:%H:%M:%S}"

    if "lookup_from" not in st.session_state:
        last_two_minutes()
    c1, c2, c3 = st.columns(3)
    cam = c1.selectbox("Camera", [f"{c.id} · {c.zone}" for c in site.cameras]).split(" · ")[0]
    start = c2.text_input("From (site time)", key="lookup_from")
    end = c3.text_input("To (site time)", key="lookup_to")
    b1, b2, _ = st.columns([1, 1, 4])
    b2.button("Last 2 minutes", on_click=last_two_minutes)
    if b1.button("Get clip"):
        try:
            path = recorder.cut_clip(cam, site.parse_time(start), site.parse_time(end))
            st.video(str(path))
        except (NotYetAvailable, ValueError) as err:
            st.warning(str(err))


# Layout ---------------------------------------------------------------------------
live, lookup = st.tabs(["Control room", "Footage lookup"])
with live:
    wall, inbox = st.columns([3, 2], gap="medium")
    with wall:
        camera_wall()
    with inbox:
        st.markdown("#### Alert inbox")
        alert_inbox()
    st.divider()
    review_panel()
with lookup:
    footage_lookup()
