## Alertes à vérifier (1)

Observations de sécurité non confirmées par la vérification automatique. Elles ne comptent pas comme événements confirmés ; un opérateur doit trancher.

1. **Possible : personne à terre** — 00:07.519700–00:08.519700
   - Pourquoi ce n'est pas confirmé : Possible, non confirmé : l'analyse vidéo soupçonne cet événement sans l'avoir vu clairement. Raison enregistrée : « Partial occlusion by the frame edge prevents observing whether the person came to lie on the floor. »
   - Images à regarder : F16 00:07.519700 (frame 182), F17 00:08.039700 (frame 195), F18 00:08.519700 (frame 207) (3 sur 3 images citées)
   - Description de la perception : « The person in the blue shirt is upright near the bottom right in F16 and appears lower and partially hidden near the image boundary in F17 and F18. It cannot be confirmed whether the person fell or stepped beyond the image edge. »
   - Question : Une personne est-elle à terre ?

# Video investigation

Initial scan: completed (scheduled through 00:41.999712 of 00:41.999712). Coverage records distinguish sampled timestamps, submitted clip spans, and uninspected time. Uninspected time provides no evidence of absence. Corroboration from two inspections using the same model is not independent semantic confirmation.

Supported findings with source citations: 3.

Lead finding: A person moved within view.

Investigation: partial. Verification: completed (4/4 checks completed). Observation triage: 8/8 accounted for. The investigation is incomplete. Unfinished checks and open observations remain unresolved.

Source: video-a0273d9465bd3c72578d6fd1bda4daf50d9591866e448b53eb3bc1ecd4d4b9d5  
SHA-256: `fafff382d83c7f091dc47396dee82159fb88c0d951b649b6f17afc2b0a914380`

This report covers only the inspected visual inputs. Citation times describe evidence. Direct visual findings use a model-assessed before/after frame pair. Action claims require corroborating observations from separate inspections.

- **00:00.000000–00:03.519700** A person moved within view. supported
  - Verification rationale (model assessment): The observation of the person in a blue shirt moving across the lobby floor from the lower right toward the center of the atrium and back is supported by the frame sequence.
  - frames `inspection-691b7b16f4609d3ac053a5fa3fc941d4f907ffe80e819ded10d104636db26742` at 00:00.000000–00:07.519700 (16 source frames).
- **00:15.039700–00:15.039700** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-774cba9d7766d94e2bb1d94feb37f2a424382e3bd65a66668dac97dac8e43c44` at 00:15.039700–00:15.039700 (1 source frames).
- **00:18.039700–00:19.519700** A person moved within view. supported
  - Verification rationale (model assessment): The cited frames demonstrate the person moving across the atrium floor between the start and end frame references.
  - frames `inspection-774cba9d7766d94e2bb1d94feb37f2a424382e3bd65a66668dac97dac8e43c44` at 00:18.039700–00:19.519700 (4 source frames).
- **00:20.039700–00:29.519700** Finding remains unresolved. unsupported
  - frames `inspection-0ba060fec77773796832435cbb0d896dba2c8fe74d890b9e38331dd7075b5792` at 00:20.039700–00:29.519700 (20 source frames).
- **00:30.039700–00:39.519700** A person moved within view. supported
  - Verification rationale (model assessment): The observation is supported by the frame inspection showing the person walking from the upper right region across the atrium floor and back.
  - frames `inspection-64ac014824fe5f0cd5860bc65096c96bf0297db422257f89fad3e41a6d0c2b03` at 00:30.039700–00:39.519700 (20 source frames).
- **00:30.039700–00:30.039700** Finding remains unresolved. insufficient. Recorded reason: Observation associated during triage.
  - frames `inspection-64ac014824fe5f0cd5860bc65096c96bf0297db422257f89fad3e41a6d0c2b03` at 00:30.039700–00:30.039700 (1 source frames).
- **00:40.039711–00:41.519700** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-59aaee3935b3942756cbb52fb8b84d375fb3bd1748b6ce78f02610957aa47703` at 00:40.039711–00:41.519700 (4 source frames).
