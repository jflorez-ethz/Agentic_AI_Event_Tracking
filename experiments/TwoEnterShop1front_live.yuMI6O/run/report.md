## Alertes à vérifier (0)

Aucune alerte de sécurité non confirmée.

### Non retenus comme alertes

- Entrée dans une zone, 00:50.520000–00:52.520000 : aucune zone surveillée n'est configurée, l'entrée dans une zone ne peut pas être vérifiée (ces alertes reviendront avec la configuration des zones).

# Video investigation

Initial scan: completed (scheduled through 01:05.800000 of 01:05.800000). Coverage records distinguish sampled timestamps, submitted clip spans, and uninspected time. Uninspected time provides no evidence of absence. Corroboration from two inspections using the same model is not independent semantic confirmation.

Supported findings with source citations: 3.

Lead finding: A person moved within view.

Investigation: partial. Verification: completed (4/4 checks completed). Observation triage: 16/18 accounted for. The investigation is incomplete. Unfinished checks and open observations remain unresolved.

Source: video-cce6dd08670c1eda7bdfd62c81acec275c59b1170bc1690f3a09d129d7753dbf  
SHA-256: `14270619fd6b25527ba361fe8b5e9657decfd8abb86a39cae6e463dbc7214deb`

This report covers only the inspected visual inputs. Citation times describe evidence. Direct visual findings use a model-assessed before/after frame pair. Action claims require corroborating observations from separate inspections.

- **00:10.000000–00:16.520000** A person moved within view. supported
  - Verification rationale (model assessment): The existing inspection description and cited frames establish the movement of the person walking along the upper-level corridor from left to right.
  - frames `inspection-69e6bf1527bf7a2cbd940aa1c300294c34e6d747827c72d80533040cdd3d704d` at 00:10.000000–00:16.520000 (14 source frames).
- **00:18.520000–00:19.520000** A person entered the observed area. supported
  - Verification rationale (model assessment): Both descriptions document the same physical crossing of two individuals across the threshold boundary into the shop interior across shared frames.
  - frames `inspection-69e6bf1527bf7a2cbd940aa1c300294c34e6d747827c72d80533040cdd3d704d` at 00:18.520000–00:19.520000 (3 source frames).
  - frames `inspection-cb3a8af303c120a86827bc8a64551b0fb431a48d68ceed8efadda3a63b59d251` at 00:18.000000–00:19.760000 (8 source frames).
- **00:21.520000–00:29.520000** A person moved within view. supported
  - Verification rationale (model assessment): The frame inspection demonstrates the person wearing a light coat walking from left to right along the walkway across the specified frame interval.
  - frames `inspection-e9c2e31425aebb67ead749d1b334d94686aca60dcd1bed0394567d4f25185fff` at 00:21.520000–00:29.520000 (17 source frames).
- **00:50.520000–00:52.520000** Finding remains unresolved. insufficient. Recorded reason: The observation describes a person\_enters\_area event, but there is no eligible corroborating description with a shared boundary phrase to satisfy the entry support criteria.
  - frames `inspection-3ea8d8a625c5cd30ee03aedd462d33e738ea325f726e5d1b2ec805dc93933cf6` at 00:50.520000–00:52.520000 (5 source frames).
- **01:03.520000–01:03.520000** Finding remains unresolved. insufficient. Recorded reason: Observation omitted during triage.
  - frames `inspection-79b3cc2ebb550992ea1436c6252ddba8bc0e9fdbb7217a1ea25a786a4e788fa3` at 01:03.520000–01:03.520000 (1 source frames).
- **01:03.520000–01:05.520000** Finding remains unresolved. insufficient. Recorded reason: Observation omitted during triage.
  - frames `inspection-79b3cc2ebb550992ea1436c6252ddba8bc0e9fdbb7217a1ea25a786a4e788fa3` at 01:03.520000–01:05.520000 (5 source frames).
