## Alertes à vérifier (1)

Observations de sécurité non confirmées par la vérification automatique. Elles ne comptent pas comme événements confirmés ; un opérateur doit trancher.

1. **Personne à terre** — 00:20.039700–00:27.519700
   - Pourquoi ce n'est pas confirmé : La vérification juge que les images ne le montrent pas. À confirmer quand même : ce type d'événement n'est jamais écarté par l'agent. Raison enregistrée : « Detailed visual inspection confirms the person bends and sits or crouches against the bench structure rather than falling to the floor, leaving the claimed fall unsupported. » (ce texte du modèle paraît affirmatif malgré le verdict non confirmé)
   - Images à regarder : F1 00:20.039700 (frame 495), F11 00:25.079700 (frame 620), F16 00:27.519700 (frame 682) (3 sur 21 images citées)
   - Description de la perception : « A person is shown standing upright in frames F1 through F11 and lying on the floor in frame F16. »
   - Question : Une personne est-elle à terre ?

# Video investigation

Initial scan: completed (scheduled through 00:36.719700 of 00:36.719700). Coverage records distinguish sampled timestamps, submitted clip spans, and uninspected time. Uninspected time provides no evidence of absence. Corroboration from two inspections using the same model is not independent semantic confirmation.

Supported findings with source citations: 1.

Lead finding: A person went from upright to lying on the floor.

Investigation: partial. Verification: completed (4/4 checks completed). Observation triage: 8/8 accounted for. The investigation is incomplete. Unfinished checks and open observations remain unresolved.

Source: video-ba8c1e5f765e6a56429b7e175e062900ae49b8f4434c12b2ccf3f8842645278d  
SHA-256: `4ac7d2c63479ce052c0b7e7f8a49aec35f971bcd9b49c78b6687c5f885daf78c`

This report covers only the inspected visual inputs. Citation times describe evidence. Direct visual findings use a model-assessed before/after frame pair. Action claims require corroborating observations from separate inspections.

- **00:00.000000–00:09.519700** Finding remains unresolved. insufficient. Recorded reason: The frame inspection confirms the movement of the person wearing a blue top and dark trousers across the atrium floor from the initial frame to the final frame.
  - frames `inspection-96072ddef8947206081db06d69ca15772da787d7addbe43aeb17d3cf00f1d3b3` at 00:00.000000–00:09.519700 (20 source frames).
- **00:00.000000–00:02.519700** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-96072ddef8947206081db06d69ca15772da787d7addbe43aeb17d3cf00f1d3b3` at 00:00.000000–00:02.519700 (6 source frames).
- **00:02.519700–00:03.039700** A person went from upright to lying on the floor. supported
  - Verification rationale (model assessment): The observation description and cited frames establish the before state (standing upright in F6) and after state (lying on the floor in F7), supporting the person\_fell event with a transition.
  - frames `inspection-96072ddef8947206081db06d69ca15772da787d7addbe43aeb17d3cf00f1d3b3` at 00:02.519700–00:03.039700 (2 source frames).
- **00:12.039700–00:12.039700** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-a9f45106c0cd8e5fc9b69a71bff25dd2d5144b838f754b8f85dacbfeb45af048` at 00:12.039700–00:12.039700 (1 source frames).
- **00:12.519700–00:19.519700** Finding remains unresolved. unsupported
  - frames `inspection-a9f45106c0cd8e5fc9b69a71bff25dd2d5144b838f754b8f85dacbfeb45af048` at 00:12.519700–00:19.519700 (15 source frames).
- **00:20.039700–00:27.519700** Finding remains unresolved. unsupported
  - frames `inspection-df9f89d3795f6a9df7c1aeb3123f303bf7f2fed6df03945843f77c5e33be93aa` at 00:20.039700–00:27.519700 (16 source frames).
  - frames `inspection-4a23ead0c78f40d5acd0ecebb3a81c05743bc427f5753fbb86fa9df4bf3c7862` at 00:25.079700–00:27.279700 (10 source frames).
- **00:20.039700–00:25.079700** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-df9f89d3795f6a9df7c1aeb3123f303bf7f2fed6df03945843f77c5e33be93aa` at 00:20.039700–00:25.079700 (11 source frames).
- **00:30.039700–00:36.519700** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-75de31b8bbdcc7ba7411e349a648a2c784102a11ba198e942098b3b700000471` at 00:30.039700–00:36.519700 (14 source frames).
