# Watch-list events

Status: draft, to be validated by the group (plan task A1).

The system describes facts; it does not interpret intent or judge
people. For every alert it gives the guard the facts, the time and the
cited images. The guard decides. The system never identifies a person;
"Person A" means an anonymous track valid within one video only.

Every alert has one of two statuses:
- **Facts verified**: the facts were checked on new images by the
  verification rules.
- **Needs guard review**: the system is not sure or the case is
  ambiguous. Ambiguous cases always go to the guard.

## Level 1 — Always notify (never dismissed)

| Event | Facts given to the guard | Detectable today |
|---|---|---|
| Person on the floor | start time; sitting or lying; how they got there (measured duration and postures, e.g. "from standing to lying in 1.2 s, via kneeling"); time on the floor; got up (when) or still on the floor | Yes |
| Object left with nobody next to it | object description; location in the image; anonymous track that placed it; time since placement | Partly: only when the object is visible |
| Smoke or fire | location; start time | No (not in CAVIAR) |

## Level 2 — Notify depending on site context

Requires configured zones and schedules (plan task C1) and site context
such as access log, roster and procedures (plan task B4).

| Event | Facts given to the guard | Detectable today |
|---|---|---|
| Person or vehicle in a monitored zone outside allowed hours | zone; time; where they came from | No (no zones yet) |
| Emergency exit or passage blocked | which passage; by what; since when | No (no zones yet) |
| Object taken back after being left | time; anonymous track that took it; link to the placement | Partly: only when the object is visible |

## Level 3 — Describe only (no alert)

Shown in the report chronology, never as an alert: person walking,
person appearing, person sitting on a seat, person kneeling.

## Wording in the guard report

Use descriptive labels, without any connotation of a crime:
"Watch-list event", "Watch-list events — facts verified",
"Needs guard review". The word "security" may remain in code only.
