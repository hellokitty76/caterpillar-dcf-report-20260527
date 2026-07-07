# 企劃書 / Proposal-writing skills

Skills pulled in from public GitHub repos for drafting proposals, contracts, grant
applications, and RFP responses.

## Installed

- **`contract-and-proposal-writer/`** — free-form business documents (proposals,
  SOWs, NDAs, MSAs) with US/EU/UK/DACH jurisdiction-aware clauses.
  Source: [borghei/Claude-Skills](https://github.com/borghei/Claude-Skills/blob/main/business-growth/contract-and-proposal-writer/SKILL.md)
- **`grant-proposal-writer/`** — funding proposal / LOI / grant application
  drafter (input checklist, donor profile lookup, reviewer-comment handling
  for resubmissions).
  Source: [chrisblattman/claudeblattman](https://github.com/chrisblattman/claudeblattman/blob/main/skills/proposal-write.md)
  (adapted into standard `SKILL.md` folder form; optional integrations like the
  voice pack and donor profiles degrade gracefully if you don't set them up —
  see "Customization Points" in the file).
- **`rfp-responder/`** — structured response to buyer-dictated RFP/RFI/RFQ:
  requirement parsing, Shipley-method proof-point matrix, win-theme strategy,
  winrate estimate, bid/no-bid verdict.
  Source: [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills/blob/main/commercial/skills/rfp-responder/SKILL.md)

All three ship with their original `scripts/`/`assets`/`references` helper files
(stdlib-only Python, no network calls) and were reviewed before being added here.

## Not installed (curated link lists, not skills)

`anthropics/skills`, `VoltAgent/awesome-agent-skills`, `ComposioHQ/awesome-claude-skills`,
and `BehiSecc/awesome-claude-skills` are indexes of links to other repos, not
skill folders themselves. None of them contained a proposal-writing skill beyond
the two above. `anthropics/skills` does ship generic `docx`/`pptx`/`xlsx`/`pdf`
document-format skills (useful for exporting a finished proposal, not for
drafting one) — install via `/plugin install document-skills@anthropic-agent-skills`
if you want those too.
