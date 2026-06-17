# Project Vision Document

## Intake Metadata
- Source form: Discovery_Call_Intake_Form_BLANK.docx
- Skill: vision-from-discovery-call
- Completed: 2026-06-17

## Raw Intake Answers

1. **Date of discovery call.**
   - Answer: June 17, 2026.

2. **Call type (Video / Phone / In-person).**
   - Answer: Mixed. Sarah Chen = in-person ("meeting with me"); Marcus Williams = in-person ("coffee chat"); Dave Morrison = in-person ("hallway conversation"); Jenny Park = video ("Teams call").

3. **Full name.**
   - Answer: Four stakeholders, no single client — Sarah Chen (Deputy Director, Label Compliance); Marcus Williams (IT Systems Admin); Dave Morrison (Senior Compliance Agent); Jenny Park (Junior Compliance Agent).

4. **Business / company name.**
   - Answer: TTB (Alcohol and Tobacco Tax and Trade Bureau), Compliance Division / Label Compliance.

5. **Email address.**
   - Answer: Not provided.

6. **Phone / WhatsApp.**
   - Answer: Not provided.

7. **Time zone.**
   - Answer: Not stated for primary contacts. Only geographic clue: a Seattle office (Janet) implying Pacific; multiple offices exist.

8. **How did you find us?**
   - Answer: Not in document.

9. **Preferred communication method.**
   - Answer: Not stated as a preference. Observed usage: Teams (Jenny's call) and email (Marcus references it).

10. **Project name / working title.**
    - Answer: "AI-Powered Alcohol Label Verification App."

11. **What does this app do in one sentence?**
    - Answer: An app that checks an alcohol label's artwork against its application data to confirm the brand name, alcohol content, and mandatory government warning all match and are valid.

12. **What problem does this solve?**
    - Answer: Agents spend roughly half their day on routine, manual "does the number on the form match the number on the label" verification across ~150,000 applications/year with only 47 agents; the goal is to automate the rote matching so staff can focus on judgment calls.

13. **Who are the end users?**
    - Answer: TTB compliance agents (~47 total). Wide tech range: from Dave (28 yrs experience, prints emails) to Jenny (recent grad, highly capable). Half the team is 50+. Usage is constant/daily — it is their core workflow.

14. **App type.**
    - Answer: Internal business tool (standalone proof-of-concept). Secondary flavor of a data/verification dashboard.

15. **Must-have features for launch (MVP).**
    - Answer: Image/label upload; brand-name match check; alcohol-content (ABV) match check; government warning verification (exact, all-caps "GOVERNMENT WARNING:"); pass/flag result output; sub-5-second response time; simple, obvious UI usable by low-tech users. **Brand and ABV matching are fuzzy/tolerant in the MVP** (resolved contradiction — see below).

16. **Nice-to-have features for Phase 2 or the future.**
    - Answer: Batch upload of 200–300 applications (high-value, strongly desired); robustness to poor images (angles, glare, bad lighting); eventual COLA workflow integration. *(Note: tolerant/fuzzy field matching was floated here in the discovery doc but has been promoted into the MVP — see One Bet / resolved contradiction.)*

17. **User roles and permission levels.**
    - Answer: Not specified. All agents perform the same task; no roles or permission tiers defined for the prototype. Likely a single standard-user role for now.

18. **Third-party integrations needed.**
    - Answer: None required for the prototype. Explicitly not integrating with COLA. Firewall blocks many outbound ML endpoints.

19. **Other integrations not listed above.**
    - Answer: None.

20. **Design style preference.**
    - Answer: Clean and minimal (implied: "clean, obvious, no hunting for buttons," "something my mother could figure out").

21. **Existing brand assets.**
    - Answer: Not addressed in the document.

22. **Competitor or inspiration URLs.**
    - Answer: ttb.gov (referenced for label requirements). A prior unnamed scanning vendor pilot is mentioned as a negative example, no URL.

23. **Colors / fonts to avoid.**
    - Answer: Not specified.

24. **Anything you specifically do not want in the design.**
    - Answer: No clutter or hidden controls; don't make the workflow harder (Dave: "don't make my life harder"); avoid the confusing-navigation failure of past tools.

25. **Technology stack preference.**
    - Answer: Open ("free to use any"). No preference stated for the prototype. Existing COLA is .NET; environment is Azure.

26. **Hosting preference.**
    - Answer: Not specified for the prototype. Their infrastructure is Azure (post-2019 migration, FedRAMP). Outbound firewall restrictions noted.

27. **Expected concurrent users at launch.**
    - Answer: Not specified. Upper bound is the ~47-agent team.

28. **Mobile / device requirement.**
    - Answer: Not specified. Agents work at desks, so desktop / responsive web is the practical implication.

29. **Does the app handle sensitive data?**
    - Answer: For the prototype, no sensitive data ("we're not storing anything sensitive"). Production would involve PII and federal retention/compliance — out of scope here.

30. **Existing systems or codebase to integrate with.**
    - Answer: COLA system (.NET, on Azure) is the system this would eventually feed into, but the prototype explicitly does not integrate with it; treat as standalone.

31. **Desired launch date.**
    - Answer: Not specified (time-boxed take-home; real integration described as "years away").

32. **Is this a hard deadline?**
    - Answer: Not specified. The exercise is time-constrained but flexible on scope.

33. **Budget range.**
    - Answer: Not provided. (The $4.2M figure was an unrelated COLA-rebuild quote, not this project.)

34. **Payment preference.**
    - Answer: Not in document.

35. **Post-launch support needed?**
    - Answer: Not specified.

36. **Red flags or scope concerns noted.**
    - Answer:
      - History of failed modernization efforts → agent skepticism and adoption risk (Dave).
      - Hard, non-negotiable 5-second performance bar; missing it killed the last pilot.
      - Scope-creep magnets: batch processing and image-enhancement floated as "would be amazing" but flagged as possibly out of scope.
      - Firewall/network constraints can silently break cloud-API approaches.
      - Roles, deadlines, budget, and success metrics are undefined/vague.
      - Multiple stakeholders with differing priorities; no single decision-maker identified.

37. **Client's biggest fear or risk.**
    - Answer: A repeat of the last pilot — a tool that's too slow or too clunky, so agents abandon it and revert to checking by eye. Performance + adoption is the core fear.

38. **How will the client define success?**
    - Answer: Agents actually use it because it's faster than the naked eye (they could do 5 labels in the time the old machine did 1); results in ~5 seconds; simple enough for the least tech-comfortable staff; accurate matching including the strict warning check.

39. **Agreed next steps from this call.**
    - Answer: Deliver a working standalone prototype — source-code repo (GitHub) with README and approach docs, plus a deployed, testable URL.

40. **Overall vibe of the call.**
    - Answer: Mixed but constructive — enthusiastic (Jenny, Sarah), cautiously skeptical but open (Dave), pragmatic and constraint-focused (Marcus).

41. **Likelihood to close.**
    - Answer: Not applicable in the sales sense — this is a take-home evaluation, not a prospect call. Framed as a deal: the "client" is committed (deliverables and evaluation criteria are defined), so engagement is effectively guaranteed; "closing" means passing the evaluation.

42. **Client signature or confirmation.**
    - Answer: None present.

43. **Developer / date.**
    - Answer: jayceparabellum / 2026-06-17.

## Vision Summary

A standalone, proof-of-concept web app that lets a TTB compliance agent upload an
alcohol label image alongside the claimed application data, then verifies — in
under five seconds — that the label's **brand name**, **alcohol content (ABV/proof)**,
and **mandatory government warning** match and are valid, returning a clear
per-field PASS/FLAG result. It automates the rote half of an agent's day so the
47-person team can spend judgment on the cases that need it, across ~150,000
applications a year. It is deliberately *not* integrated with COLA or any
government system; it is a self-contained demonstration of the core verification
loop, built to survive a locked-down (no outbound ML/cloud) environment through
local processing.

## One Bet That Matters

> **Agents trust the tool's verdicts enough to use it instead of their own eyes —
> because it's faster and clearer.**

Adoption is the entire game. The last pilot died at 30–40 seconds per label and a
confusing UI; agents reverted to eyeballing. Everything in the MVP exists to win
the bet that a fast (<5s), obvious, accurate tool will actually get used by the
least tech-comfortable agent on the team — not just impress the technical ones.
Speed, trust (correct fuzzy-vs-strict matching), and usability are the three legs;
remove any one and the bet fails.

## Problem

TTB compliance agents spend roughly half their working day on mechanical
verification — confirming the brand name, ABV, and government warning on a label's
artwork match the submitted application — across ~150,000 applications per year
with only 47 agents. The work is high-volume, repetitive, and a poor use of expert
judgment. A previous vendor tool meant to help was too slow (30–40s/label) and too
clunky, so it was abandoned and staff went back to doing it by eye. The pain is
felt most acutely by front-line agents (the bulk of the day) and by leadership
watching skilled staff bottlenecked on rote matching.

## Target Users

TTB compliance agents — about 47 of them — using the tool constantly as their core
daily workflow. The population spans the full tech-comfort spectrum: from Dave
Morrison (28 years in, prints his emails, skeptical after past failed
modernizations) to Jenny Park (recent grad, highly capable). Roughly half the team
is 50+. The binding usability constraint is the least tech-comfortable user, not
the average one: if Dave won't use it, it failed. Stakeholders include Sarah Chen
(Deputy Director, sponsor), Marcus Williams (IT, focused on the Azure/FedRAMP/
firewall constraints), and the agents themselves as the daily users.

## MVP Candidate

A single-screen web app delivering one verification at a time:

- **Upload** a label image plus the claimed fields (brand name, ABV/proof, expected
  government warning).
- **OCR** the label locally (no outbound calls).
- **Brand name** — fuzzy/tolerant match (case-, punctuation-, whitespace-
  insensitive); `STONE'S THROW` matches `Stone's Throw`.
- **Alcohol content** — numeric-tolerant match on ABV (and proof = 2×ABV), so
  `5%`, `5.0%`, `ALC 5.0% BY VOL` all match a claimed `5.0`.
- **Government warning** — strict, exact, all-caps `GOVERNMENT WARNING:` plus the
  official 27 CFR §16.21 wording; title-case or altered wording = FAIL.
- **Result view** — per-field PASS/FLAG showing found vs expected, clearly.
- **Performance** — end-to-end under 5 seconds per label.
- **Usability** — clean, minimal, large targets, obvious next step; usable by the
  least tech-comfortable agent.

## Phase 2 / Future Parking Lot

- Batch upload of 200–300 applications at once (high-value, strongly desired).
- Robustness to poor image quality — angle, glare, lighting correction.
- COLA workflow integration (the eventual destination; .NET on Azure; years away).
- Auth, user roles/permissions, and production security/compliance.
- Federal data retention, PII handling, and FedRAMP production posture.

## Design Direction

Clean and minimal — "something my mother could figure out." No clutter, no hidden
controls, no multi-step hunting for buttons. Large targets, high contrast, one
obvious path from upload to result. Explicitly avoid the confusing navigation that
sank past tools. No brand assets provided; default to a neutral, accessible,
government-appropriate look. Responsive web, desktop-primary (agents work at desks).

## Technical Direction

Stack is open; chosen for the constraints: **Python (FastAPI)** backend, **Tesseract
OCR (pytesseract)** for fully local text extraction, **rapidfuzz** for fuzzy field
matching, exact string logic for the warning, and a **server-rendered UI**
(Jinja2 + vanilla CSS) to keep it simple and dependency-light. No database;
stateless, ephemeral processing (no label storage). The decisive constraint is the
**locked-down network**: the deployment environment blocks outbound ML/cloud APIs,
so all processing must be local — this is why Tesseract is preferred over cloud
vision. Their production environment is Azure (FedRAMP); the prototype deploys to a
public shareable URL (Render via Docker, which bundles the Tesseract binary).

## Integrations

None in the prototype. Explicitly **no COLA integration** (the eventual .NET/Azure
destination is out of scope). No third-party APIs, no payments, no auth providers.
Outbound firewall restrictions are a hard environmental fact the design respects by
staying local.

## Data Sensitivity, Risks, and Trust Concerns

- **Data:** No sensitive data in the prototype; nothing stored; processing is
  ephemeral. Production PII/federal-retention concerns are explicitly out of scope.
- **Adoption risk:** History of failed modernization → agent skepticism (Dave). The
  tool must visibly beat the naked eye to earn trust.
- **Performance risk:** The 5-second bar is non-negotiable; the last pilot died at
  30–40s.
- **Network risk:** Cloud-API approaches can silently break behind the firewall —
  mitigated by local processing.
- **Accuracy/trust risk:** Getting fuzzy-vs-strict matching right is what makes
  verdicts trustworthy — false flags erode trust as fast as misses.
- **Known limitation:** The warning legally must also be **bold**, but bold is
  unreliable to detect from a photo via OCR; this is documented and intentionally
  handled/skipped rather than faked.
- **Governance risk:** Multiple stakeholders, differing priorities, no single
  decision-maker; success metrics, budget, and deadline are loosely defined.

## Timeline and Budget

Time-boxed take-home exercise; no fixed launch date, hard deadline, budget, payment
terms, or post-launch support specified. Real COLA integration is described as
"years away." The $4.2M figure mentioned in discovery was an unrelated COLA-rebuild
quote, not this project. Scope is flexible; the constraint is proving the core loop
well, not shipping production.

## Measurable Success

- **Speed:** end-to-end verification result in **< 5 seconds** per label (measured).
- **Throughput feel:** demonstrably faster than the naked eye (the "5 labels in the
  time the old tool did 1" framing).
- **Usability:** the least tech-comfortable agent can complete a verification with
  no training and no hunting for controls.
- **Accuracy:** correct PASS/FLAG decisions, including tolerant brand/ABV matching
  (`STONE'S THROW` == `Stone's Throw`) and strict all-caps warning matching
  (title-case `Government Warning` = FAIL).
- **Deliverable:** a clean GitHub repo with README/approach docs and a deployed,
  testable public URL.

## Immediate Next Steps Before Planning

1. Confirm this PVD reflects the vision (this document).
2. Move to the PRD stage: draft `PRD-v1.md` (v1-only, focused on the one bet).
3. Verify (don't paraphrase) the exact 27 CFR §16.21 government warning text from an
   authoritative source before locking matching logic.
4. Confirm deployment target (Render via Docker assumed) so the public URL
   deliverable is reachable behind the local-processing constraint.
5. Lock MVP scope against the Phase 2 parking lot to resist scope creep (batch +
   image-enhancement stay parked).

## Next-Stage Prompts

From PVD.md, draft PRD-v1.md as a v1-only PRD. Include: problem, 3-5 user stories (as a... / I want... / so that...), in-scope vs out-of-scope, and measurable success. Cut what isn't needed to prove the one bet that matters - that people trust the AI's priorities; park the rest as out-of-scope. Ask before assuming. After PRD-v1.md is accepted, export the final PRD product as PRD.pdf to the user's Desktop area.

From PRD-v1.md, build a Now / Next / Later roadmap. Sequence by risk x value, not by excitement. "Now" = only what tests the riskiest assumption - do users trust the AI's priorities? One line of rationale per item; keep Next and Later deliberately loose.
