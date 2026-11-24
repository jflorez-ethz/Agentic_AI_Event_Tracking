## Alertes à vérifier (1)

Observations de sécurité non confirmées par la vérification automatique. Elles ne comptent pas comme événements confirmés ; un opérateur doit trancher.

1. **Possible : objet retiré** — 00:30.039700–00:39.519700
   - Pourquoi ce n'est pas confirmé : Possible, non confirmé : l'analyse vidéo soupçonne cet événement sans l'avoir vu clairement. Raison enregistrée : « The physical removal action cannot be confirmed due to body occlusion during frames F11 to F15. »
   - Images à regarder : F1 00:30.039700 (frame 747), F10 00:34.519700 (frame 859), F11 00:35.039700 (frame 872), F14 00:36.519700 (frame 909), F16 00:37.519700 (frame 934), F20 00:39.519700 (frame 984) (6 sur 9 images citées)
   - Description de la perception : « A dark object rests on the floor beside an armchair in frames F1 to F10. In frames F11 to F14, the person bends over near the object, partially obscuring the physical action of picking it up. By frame F16, the object is no longer on the floor at that spot and moves with the person. »
   - Question : Un objet est-il retiré ?

# Video investigation

Initial scan: completed (scheduled through 00:44.799700 of 00:44.799700). Coverage records distinguish sampled timestamps, submitted clip spans, and uninspected time. Uninspected time provides no evidence of absence. Corroboration from two inspections using the same model is not independent semantic confirmation.

Supported findings with source citations: 4.

Lead finding: A person moved within view.

Investigation: partial. Verification: completed (4/4 checks completed). Observation triage: 10/10 accounted for. The investigation is incomplete. Unfinished checks and open observations remain unresolved.

Source: video-5e3dff99a6c0aecb225e776c14943364177627cd05d154c69b17ceb62aeb8ef5  
SHA-256: `f71c3816a7410c3972241af41fa975094370f90486246c5b9c0a88899f1ea727`

This report covers only the inspected visual inputs. Citation times describe evidence. Direct visual findings use a model-assessed before/after frame pair. Action claims require corroborating observations from separate inspections.

- **00:00.000000–00:09.519700** A person moved within view. supported
  - Verification rationale (model assessment): The available frame inspection establishes the movement of the person wearing a blue shirt and dark trousers across the floor area between the start and end frames.
  - frames `inspection-b7a01d3c257521bf2d24769d2d29fd700517c44a629f63b5d35759ab9412e70b` at 00:00.000000–00:09.519700 (20 source frames).
- **00:00.000000–00:02.039700** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-b7a01d3c257521bf2d24769d2d29fd700517c44a629f63b5d35759ab9412e70b` at 00:00.000000–00:02.039700 (5 source frames).
- **00:10.039700–00:19.519700** A person moved within view. supported
  - Verification rationale (model assessment): The frame evidence establishes that the person moved from the upper right side of the atrium at F1 to the seating area on the left side at F20.
  - frames `inspection-4683cb7358e79139d7086ae9b5b695ebbcfdf73f4040b17c88602b1a24b3de2f` at 00:10.039700–00:19.519700 (20 source frames).
- **00:10.039700–00:10.039700** Finding remains unresolved. insufficient. Recorded reason: Observation associated during triage.
  - frames `inspection-4683cb7358e79139d7086ae9b5b695ebbcfdf73f4040b17c88602b1a24b3de2f` at 00:10.039700–00:10.039700 (1 source frames).
- **00:20.039700–00:20.039700** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-74d22e459d0acec442adfe52a4b0aa54d0fa7d974debd1d19a998836524f6bcf` at 00:20.039700–00:20.039700 (1 source frames).
- **00:20.039700–00:24.519700** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-74d22e459d0acec442adfe52a4b0aa54d0fa7d974debd1d19a998836524f6bcf` at 00:20.039700–00:24.519700 (10 source frames).
- **00:30.519700–00:39.519700** A person moved within view. supported
  - Verification rationale (model assessment): The frame inspection provided initial and final frames showing the movement of the person across the atrium lobby floor.
  - frames `inspection-d96ffd3ff57e2864c47f0a865ec8a97dcce34909378bd466888ad88058b6d643` at 00:30.519700–00:39.519700 (19 source frames).
- **00:30.519700–00:30.519700** Finding remains unresolved. insufficient. Recorded reason: Observation associated during triage.
  - frames `inspection-d96ffd3ff57e2864c47f0a865ec8a97dcce34909378bd466888ad88058b6d643` at 00:30.519700–00:30.519700 (1 source frames).
- **00:40.039700–00:44.519700** A person moved within view. supported
  - Verification rationale (model assessment): The frame sequence establishes the person's movement from near the center of the lobby floor at 40039700 us to the bottom right at 44519700 us.
  - frames `inspection-6088205bd46c3a0cbe8f098a6b75ef1c5a141a64dc31514e7c19c5105a4246c6` at 00:40.039700–00:44.519700 (10 source frames).
