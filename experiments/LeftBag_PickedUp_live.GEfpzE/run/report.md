## Alertes à vérifier (1)

Observations de sécurité non confirmées par la vérification automatique. Elles ne comptent pas comme événements confirmés ; un opérateur doit trancher.

1. **Objet déposé** — 00:18.039700–00:19.519711
   - Pourquoi ce n'est pas confirmé : La vérification n'a pas pu obtenir de nouvelles images : celles demandées avaient déjà toutes été examinées. Raison enregistrée : « The request adds no source frames. »
   - Images à regarder : F17 00:18.039700 (frame 445), F18 00:18.519711 (frame 457), F19 00:19.039700 (frame 470), F20 00:19.519711 (frame 482) (4 sur 4 images citées)
   - Description de la perception : « The person carrying a black bag in hand (F17, F18) bends down and sets the black bag onto the floor by the display stand (F19, F20). »
   - Question : Un objet est-il posé puis laissé sur place ?

# Video investigation

Initial scan: partial (scheduled through 00:30.000000 of 00:54.479712). Coverage records distinguish sampled timestamps, submitted clip spans, and uninspected time. Uninspected time provides no evidence of absence. Corroboration from two inspections using the same model is not independent semantic confirmation.

Supported findings with source citations: 1.

Lead finding: A person moved within view.

Investigation: partial. Verification: partial (2/4 checks completed). Observation triage: 6/6 accounted for. The investigation is incomplete. Unfinished checks and open observations remain unresolved.

Source: video-0ee86dfb71bd00382e8f59870e8d1261bce163376077e4020925e9f266ef33e6  
SHA-256: `39e1ad6e486460aaa2a99a7df55bc366f4d744620f4ce0f85195a9b251ce2aa2`

This report covers only the inspected visual inputs. Citation times describe evidence. Direct visual findings use a model-assessed before/after frame pair. Action claims require corroborating observations from separate inspections.

- **00:00.000000–00:00.000000** Finding remains unresolved. insufficient. Recorded reason: The person is already present in the initial frame of the video at timestamp 0, so the state prior to camera start is unobserved and no before-frame exists to establish an appearance transition.
  - frames `inspection-e40463cf6acbb995caf7364404020d9a73b5785440cc10c0c26929c540f1aab3` at 00:00.000000–00:00.000000 (1 source frames).
- **00:11.519711–00:11.519711** Finding remains unresolved. insufficient. Recorded reason: Invalid verdict or citation.
  - frames `inspection-8a314e885d36cccb75df40a6475254807ff23e603c7425a310eb3d32b0221e85` at 00:11.519711–00:11.519711 (1 source frames).
- **00:18.039700–00:19.519711** Finding remains unresolved. insufficient. Recorded reason: The request adds no source frames.
  - frames `inspection-8a314e885d36cccb75df40a6475254807ff23e603c7425a310eb3d32b0221e85` at 00:18.039700–00:19.519711 (4 source frames).
- **00:20.039700–00:29.519711** A person moved within view. supported
  - Verification rationale (model assessment): The observation describes a person wearing a light blue shirt and dark pants moving across the atrium floor from near the upper partition display in frame F1 to the right side of the atrium in frame F20, supported by the frame sequence.
  - frames `inspection-c0842d72cd319a27f45fbc0676ba7111774ab98ed853a65d159c15669b003097` at 00:20.039700–00:29.519711 (20 source frames).
