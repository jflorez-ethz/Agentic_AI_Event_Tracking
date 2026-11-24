## Alertes à vérifier (1)

Observations de sécurité non confirmées par la vérification automatique. Elles ne comptent pas comme événements confirmés ; un opérateur doit trancher.

1. **Possible : personne à terre** — 00:20.039700–00:22.039700
   - Pourquoi ce n'est pas confirmé : Possible, non confirmé : l'analyse vidéo soupçonne cet événement sans l'avoir vu clairement. Raison enregistrée : « Without prior frames showing the person standing upright, it is uncertain whether a fall occurred. »
   - Images à regarder : F1 00:20.039700 (frame 496), F2 00:20.519700 (frame 508), F5 00:22.039700 (frame 546) (3 sur 5 images citées)
   - Description de la perception : « A person in dark clothing is observed sitting or crouching on the floor in F1 before getting up in F2 through F5. Because the person is not shown upright prior to F1, a fall cannot be confirmed. »
   - Question : Une personne est-elle à terre ?

# Video investigation

Initial scan: completed (scheduled through 00:38.599700 of 00:38.599700). Coverage records distinguish sampled timestamps, submitted clip spans, and uninspected time. Uninspected time provides no evidence of absence. Corroboration from two inspections using the same model is not independent semantic confirmation.

Supported findings with source citations: 4.

Lead finding: A person went from upright to lying on the floor.

Investigation: partial. Verification: completed (4/4 checks completed). Observation triage: 9/9 accounted for. The investigation is incomplete. Unfinished checks and open observations remain unresolved.

Source: video-8c3ca634217c4602c0888b7c3923c1fcc7a7180bdaa310b07bcead14793c9c54  
SHA-256: `79e5bb85695611ce73246678d87710b582d79767894247118a79dc9790bf0147`

This report covers only the inspected visual inputs. Citation times describe evidence. Direct visual findings use a model-assessed before/after frame pair. Action claims require corroborating observations from separate inspections.

- **00:04.519700–00:05.039700** A person became visible. supported
  - Verification rationale (model assessment): The candidate observation is supported by frame evidence showing the appearance of a person in dark clothing at the bottom right edge of the frame, transitioning from partially visible to fully visible between frame-c57530c4fdaceb7e87f0f33f
  - frames `inspection-aca9d0eaabd1910307d725a5cd089e26704d677abf59bf7ad5b4676612a85816` at 00:04.519700–00:05.039700 (2 source frames).
- **00:05.039700–00:09.519700** A person moved within view. supported
  - Verification rationale (model assessment): The cited frames confirm the person in dark clothing moving from the lower right toward the center of the atrium floor.
  - frames `inspection-aca9d0eaabd1910307d725a5cd089e26704d677abf59bf7ad5b4676612a85816` at 00:05.039700–00:09.519700 (10 source frames).
- **00:06.039700–00:06.519700** A person became visible. supported
  - Verification rationale (model assessment): The evidence frames show the transition from partially visible at the frame edge to fully visible in frame.
  - frames `inspection-aca9d0eaabd1910307d725a5cd089e26704d677abf59bf7ad5b4676612a85816` at 00:06.039700–00:06.519700 (2 source frames).
- **00:06.519700–00:09.519700** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-aca9d0eaabd1910307d725a5cd089e26704d677abf59bf7ad5b4676612a85816` at 00:06.519700–00:09.519700 (7 source frames).
- **00:12.519700–00:14.519700** A person went from upright to lying on the floor. supported
  - Verification rationale (model assessment): The observation describes a person standing upright in frame F6 (frame-a6b3ba7fb6b44baf2ca2277164a781cb9d351b30df5e733562e651eeddf11450) and lying on the floor in frame F10 (frame-3220ffdfa18bfd1e4cc90f9e496cf1479ef1334c69aaacd717c9179b9810
  - frames `inspection-c957f8735fc13ba52358bb393d72459b24f6905fe44650f18cd0d8c286a349e0` at 00:10.039700–00:18.519700 (18 source frames).
- **00:20.039700–00:28.039700** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-fb3c09db5cbfee6e3a1220996042f8388d1fe31db11c0e8f374b99872f72caff` at 00:20.039700–00:28.039700 (17 source frames).
- **00:20.039700–00:24.039700** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-fb3c09db5cbfee6e3a1220996042f8388d1fe31db11c0e8f374b99872f72caff` at 00:20.039700–00:24.039700 (9 source frames).
- **00:30.039700–00:32.039700** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-a9d6e0dd1964764c7ceb3847e93b17f96a4e921c3c5916c4c4aefd350e9db453` at 00:30.039700–00:32.039700 (5 source frames).
