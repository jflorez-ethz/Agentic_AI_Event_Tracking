## Alertes à vérifier (1)

Observations de sécurité non confirmées par la vérification automatique. Elles ne comptent pas comme événements confirmés ; un opérateur doit trancher.

1. **Possible : personne à terre** — 00:11.039700–00:12.519700
   - Pourquoi ce n'est pas confirmé : Possible, non confirmé : l'analyse vidéo soupçonne cet événement sans l'avoir vu clairement. Raison enregistrée : « Cannot distinguish between bending, crouching, or falling due to occlusion at the frame boundary. »
   - Images à regarder : F3 00:11.039700 (frame 270), F6 00:12.519700 (frame 307) (2 sur 4 images citées)
   - Description de la perception : « The person lowers posture near the bottom right edge of the frame, but because the subject becomes partially obscured by the image boundary, there is insufficient evidence to establish whether a fall occurred. »
   - Question : Une personne est-elle à terre ?

# Video investigation

Initial scan: completed (scheduled through 00:40.559700 of 00:40.559700). Coverage records distinguish sampled timestamps, submitted clip spans, and uninspected time. Uninspected time provides no evidence of absence. Corroboration from two inspections using the same model is not independent semantic confirmation.

Supported findings with source citations: 4.

Lead finding: A person went from upright to lying on the floor.

Investigation: completed. Verification: completed (4/4 checks completed). Observation triage: 11/11 accounted for.

Source: video-d6861e095a82bfff88df615021e8f769ab6834dbf9abaf6ef3d153a74bafb0f5  
SHA-256: `06bc1d99e6766fd755adc215b3b5753f26d099f45c6578eee9c318e5c9637546`

This report covers only the inspected visual inputs. Citation times describe evidence. Direct visual findings use a model-assessed before/after frame pair. Action claims require corroborating observations from separate inspections.

- **00:00.000000–00:09.519700** A person moved within view. supported
  - Verification rationale (model assessment): The observation describes a person in a blue shirt and dark pants moving around the central lobby area, which is confirmed by position changes across the cited frames.
  - frames `inspection-e88c08c01b56dd9989336e3ff0fff81bf4e78406ede3db1a1325490a37fe7e02` at 00:00.000000–00:09.519700 (20 source frames).
- **00:20.519700–00:26.039700** A person moved within view. supported
  - Verification rationale (model assessment): The observation establishes that the person moves across the atrium floor between frame F1 (start) and frame F12 (end).
  - frames `inspection-36cf313b6e1ff8af521c659ca0920ec925f46881e7f253f41f1779934b703286` at 00:20.519700–00:26.039700 (12 source frames).
- **00:25.519700–00:28.039700** A person went from upright to lying on the floor. supported
  - Verification rationale (model assessment): The observation is supported by the frame sequence showing the person upright before falling and lying on the floor afterwards, corroborated by observation-ae46fd89cfb73b01f7af7977ed67c10a55e571bbaa154f2cfb66eca514b5fd14.
  - frames `inspection-36cf313b6e1ff8af521c659ca0920ec925f46881e7f253f41f1779934b703286` at 00:25.519700–00:29.519700 (9 source frames).
- **00:30.039700–00:36.039700** A person moved within view. supported
  - Verification rationale (model assessment): The observation describes a person transitioning from lying prone on the floor to sitting up, standing, and walking across the atrium floor, which is corroborated by frames showing the before and after states of movement across the event in
  - frames `inspection-844bef831ce95ede3a8233c3672c5e300272030b8bd0d7ab647d76e4a04fa4e0` at 00:30.039700–00:39.519700 (6 source frames).
