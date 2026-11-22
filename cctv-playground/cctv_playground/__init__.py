"""Fake recorder for replaying recorded clips as if they were live CCTV.

Pieces:
- site.py      the footage index: which file holds which camera at which site time
- clock.py     the replay clock: what time it is "now" on the site
- recorder.py  cuts clips and frames from the camera files, never after "now"
- context.py   access log, roster and procedures, on the same clock
- tools.py     the functions an agent is allowed to call
- detector.py  stand-in detector that fires on labelled events
- triage_stub.py  stand-in triage logic, to be replaced by the real agent
- alerts.py    the alert inbox shared by the runner and the screen
"""
