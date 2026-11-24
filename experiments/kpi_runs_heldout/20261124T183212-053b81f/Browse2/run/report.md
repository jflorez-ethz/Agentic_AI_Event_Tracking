## Alertes à vérifier (1)

Observations de sécurité non confirmées par la vérification automatique. Elles ne comptent pas comme événements confirmés ; un opérateur doit trancher.

1. **Possible : objet déposé** — 00:30.000000–00:31.000000
   - Pourquoi ce n'est pas confirmé : Possible, non confirmé : l'analyse vidéo soupçonne cet événement sans l'avoir vu clairement. Raison enregistrée : « Uncertain whether the person placed the case or if it was already located there prior to frame F1. »
   - Images à regarder : F1 00:30.000000 (frame 744), F2 00:30.520000 (frame 757), F3 00:31.000000 (frame 769) (3 sur 3 images citées)
   - Description de la perception : « A person is standing next to a black case on the floor in F1-F2 before walking away in F3, but the physical action of placing the object on the floor is not visible. »
   - Question : Un objet est-il posé puis laissé sur place ?

# Video investigation

Initial scan: completed (scheduled through 00:35.280000 of 00:35.280000). Coverage records distinguish sampled timestamps, submitted clip spans, and uninspected time. Uninspected time provides no evidence of absence. Corroboration from two inspections using the same model is not independent semantic confirmation.

Supported findings with source citations: 4.

Lead finding: A person moved within view.

Investigation: partial. Verification: completed (4/4 checks completed). Observation triage: 9/9 accounted for. The investigation is incomplete. Unfinished checks and open observations remain unresolved.

Source: video-4e33155ef287b0325848d628b974654e9b2078c54d55bbddd944c48521955171  
SHA-256: `08b08b71f8b50c18aec547ac2059a6dded09ae6cc60d01bee30ca498543c7d62`

This report covers only the inspected visual inputs. Citation times describe evidence. Direct visual findings use a model-assessed before/after frame pair. Action claims require corroborating observations from separate inspections.

- **00:01.520000–00:08.520000** A person moved within view. supported
  - Verification rationale (model assessment): The cited frames establish the movement of the person wearing a blue shirt across the lobby area from the start to the end of the specified interval.
  - frames `inspection-6fb9abff810dd5e089515533f6d3c3fba6c13916366ce54d9ff76bb063cf01c4` at 00:01.520000–00:08.520000 (15 source frames).
- **00:01.520000–00:01.520000** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-6fb9abff810dd5e089515533f6d3c3fba6c13916366ce54d9ff76bb063cf01c4` at 00:01.520000–00:01.520000 (1 source frames).
- **00:10.000000–00:10.000000** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-b9211bfa203b7c36d1011d65eb6c6909cb6b15f5e92f3e111151b5b4c7aa61f7` at 00:10.000000–00:10.000000 (1 source frames).
- **00:12.520000–00:12.520000** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-b9211bfa203b7c36d1011d65eb6c6909cb6b15f5e92f3e111151b5b4c7aa61f7` at 00:12.520000–00:12.520000 (1 source frames).
- **00:13.000000–00:19.520000** A person moved within view. supported
  - Verification rationale (model assessment): The cited frame inspection establishes the initial and final positions of the person moving across the atrium floor.
  - frames `inspection-b9211bfa203b7c36d1011d65eb6c6909cb6b15f5e92f3e111151b5b4c7aa61f7` at 00:13.000000–00:19.520000 (14 source frames).
- **00:20.000000–00:22.520000** A person moved within view. supported
  - Verification rationale (model assessment): The observed movement of the person in the red shirt across the atrium floor to the kiosk is established by the frame sequence, showing the initial position in frame-610a0687ba5061611a4f0a81f855b90e80acc3a51252efdae76ea0a92a59cbd8 and final
  - frames `inspection-dc14b08b3388051b11aeb4bab452b5d9748670f147592384949df212997aeb34` at 00:20.000000–00:22.520000 (6 source frames).
- **00:20.000000–00:20.000000** Finding remains unresolved. insufficient. Recorded reason: Observation deferred during triage.
  - frames `inspection-dc14b08b3388051b11aeb4bab452b5d9748670f147592384949df212997aeb34` at 00:20.000000–00:20.000000 (1 source frames).
- **00:30.000000–00:34.000000** A person moved within view. supported
  - Verification rationale (model assessment): The observation describes a person in a red shirt and light pants moving from the right near a black case toward the upper area, which is established by the initial position at frame-f3b62213d9e71a9264db79c7c0d37adc95227b282183f607f55b0bd36
  - frames `inspection-765f364a99bf49ca9a8dfaf323015994585860f03a6975575dad2019a1f56e64` at 00:30.000000–00:34.000000 (9 source frames).
