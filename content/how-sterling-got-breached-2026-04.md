---
title: "How Sterling Bank Got Breached — And Why 60% of Nigerian Enterprises Are Next"
date: 2026-04-18
author: Securva Research
meta_description: "A single unpatched vulnerability on a testing server gave an attacker 9 days inside Sterling Bank, 3 terabytes of customer KYC data, and a pivot into Remita, Nigeria's public-sector payment processor. The attack is not sophisticated. It's the same six structural weaknesses hiding in most Nigerian enterprises right now. Here's the pattern — and what to do about it."
tags: [security, NDPA, Nigeria, banking, infrastructure, compliance, breach]
---

# How Sterling Bank Got Breached — And Why 60% of Nigerian Enterprises Are Next

On March 18, 2026, an attacker sent a specially-crafted HTTP request to an internet-facing testing server owned by Sterling Bank. The server was running an unpatched version of a component with a publicly-disclosed vulnerability (CVE-2025-55182), a maximum-severity remote-command-execution bug that had been in the public domain for three months. Within minutes, the attacker had shell access. Nine days later, they had extracted roughly 3 terabytes of data, pivoted laterally into Remita — the payment processor that handles Nigerian government salaries and a large share of public-sector transactions — and positioned the haul for ransom negotiations.

Sterling Bank said nothing to its customers. Remita said nothing to its customers. On April 1, the Nigeria Data Protection Commission served a Notice of Investigation. As of this writing, most of the roughly 900,000 Sterling Bank customers whose data is in the breach remain uninformed.

This is not a story about an advanced persistent threat. It is not a story about a zero-day. It is a story about **six structural weaknesses** that were already known, already documented, already fixable — and that are sitting in the majority of Nigerian enterprises right now.

We ran a public-infrastructure scan across 20 major Nigerian organizations over the last 30 days. **Sixty-four percent of their live hosts present at least three of the six weaknesses that put Sterling on the attack path.** The sectors the NDPC enforcement cascade has not yet reached — telecom, healthcare, e-commerce — are the ones most exposed.

This post walks through what happened at Sterling Bank in plain language, extracts the six-factor pattern, maps it against the broader Nigerian infrastructure landscape using our own data, and gives every security lead and CTO a concrete checklist for where to look first in their own organization.

---

## Part 1 — what actually happened at Sterling Bank

The attack, as reconstructed from public reporting by the threat actor (who uses the handle ByteToBreach) and corroborated by journalists at Technext24, Guardian Nigeria, and others, followed four stages:

**Stage one: perimeter compromise.** Sterling Bank operated an internet-facing testing server. The server ran a component with CVE-2025-55182, a publicly-disclosed remote code execution vulnerability. The fix had been available for three months. The patch had not been applied. On March 18, the attacker sent one request and had shell access.

**Stage two: internal reconnaissance and persistence.** The attacker spent nine days inside Sterling's systems. During that window they located a code repository that stored production credentials for Remita — in plaintext, in files that should never have been in the repository.

**Stage three: lateral pivot to a third party.** Using the plaintext Remita credentials, the attacker moved into Remita's infrastructure without ever directly attacking it. Remita was not the target. It was collateral damage from a decision Sterling Bank made about how to store sensitive information.

**Stage four: cloud-storage exfiltration.** From inside the combined Sterling+Remita environment, the attacker located a misconfigured Amazon S3 bucket. They extracted 3 terabytes of data. More than 800 gigabytes of the exfiltration was Know Your Customer material: passports, driver's licenses, national ID cards, utility bills. The rest was databases, transaction logs, internal source code, API keys, and password hashes.

No one specific decision caused the breach. Every stage was enabled by a distinct operational gap. Remove any one stage and the next one stops. Every stage is a well-understood class of failure with standard mitigations that have been industry practice for years.

---

## Part 2 — the six-factor vulnerability signature

The same pattern shows up in every breach of this class. We have seen it in the Sterling/Remita case. We have seen it in the Corporate Affairs Commission breach (25 million documents exposed via sequential-ID enumeration, announced two weeks later in a single vague statement). We have seen it in the MTN Group breach of Q2 2025 (multi-market telecom, centralised backend, customer data accessed, notification minimal). We have seen it across our own disclosure pipeline — Flutterwave, Esusu, and half a dozen smaller Nigerian fintech operators whose production credentials we found in public GitHub repositories.

The pattern distils into six structural factors. Any Nigerian organization presenting three or more of these is operating at the same risk profile as Sterling Bank on March 17, 2026.

### Factor 1 — a legacy infrastructure tier that nobody is patching

Most Nigerian enterprises of any size run two generations of infrastructure in parallel. The customer-facing layer is modern — React frontends, Next.js server-side rendering, Node.js APIs. Behind it, the internal-facing layer is legacy — Windows Server with IIS, ASP.NET applications a decade old, PHP admin panels, jQuery-based dashboards.

The legacy tier is where the patches don't land. Nobody on the current team wrote it. The original developers have moved on. There is no CI pipeline automating updates. There is no test suite that would catch a regression from a security patch. The legacy tier becomes a fossil layer, and every publicly-disclosed CVE that touches it is a live fuse.

Sterling Bank's testing server was almost certainly on this tier. A testing server running unpatched for three months on an internet-facing IP is not a sign of an under-resourced institution — it is a sign of an institution that does not have anyone whose job includes "check which internal servers are internet-facing and whether their components are patched."

### Factor 2 — missing HTTP Strict Transport Security (HSTS) on customer-facing hosts

HSTS is a security header that instructs browsers to only communicate with a site over encrypted HTTPS. It prevents an attacker on the same Wi-Fi network from silently downgrading a victim to unencrypted HTTP and intercepting their session.

HSTS has been an industry standard since 2012. Implementation is one line of web-server configuration.

Our Phase 1 infrastructure scan across 20 major Nigerian enterprises found 1,180 alive hosts. **Four hundred and twenty-five of them — 36 percent — had HSTS enabled. Seven hundred and fifty-five of them — 64 percent — did not.**

Missing HSTS does not cause a Sterling-style breach directly. But it is a reliable marker of general security posture. Organizations that have not configured a 2012-era header on 64 percent of their hosts have not invested in the processes that would also catch unpatched legacy servers.

### Factor 3 — forgotten and shadow infrastructure

Our scan found 57 hosts displaying default web server pages. These are "Welcome to nginx" and "IIS Windows Server" screens — the generic placeholder content that ships with a fresh installation.

Every one of these is a subdomain that was assigned DNS, pointed at a server, and then forgotten. The team moved on. Nobody took down the DNS record. Nobody decommissioned the host.

Default installations often ship with known vulnerabilities, debug features turned on, and administrative interfaces accessible. A forgotten subdomain is an attacker's dream surface because it gets all the defaults and none of the attention. Sterling's testing server was functionally identical to one of these.

### Factor 4 — concentrated ASN ownership with many edge hosts

Infrastructure mapping at the autonomous-system-number (ASN) level reveals how much surface each institution owns. In our Phase 2 mapping of 1,438 unique Nigerian IPs:

- Zenith Bank operates 132 hosts under its own ASN
- First Bank operates 132 under FBN-AS
- GTBank operates 89 under GTB-AS
- MTN Nigeria operates 67 under VCG-AS
- Access Bank operates a smaller but still-notable footprint

Each host is a potential entry point. A single unpatched edge host in a 132-host ASN is structurally equivalent to Sterling's testing server. The attack math is the same — the attacker only needs one. And the defender has 132 places to look.

### Factor 5 — developer repositories that leak production credentials

Every Nigerian fintech operator we have disclosed to in the past 30 days — and every one we are currently drafting letters for — had the same failure mode: a developer or small team committed a `.env` file (often `.env.production`) to a public GitHub repository, with live production credentials inside. We have found keys for Paystack, Flutterwave, Monnify, Seerbit, Korapay, Quidax, Dojah, Stripe, Supabase service-role tokens, Upstash Redis tokens, and Sentry DSNs. We have found Ethereum private keys, BIP39 mnemonics, Alchemy keys. We have found them in repositories owned by solo founders, small teams, and — in the Sterling/Remita case — inside a major-bank internal repository where the Remita credentials were stored in plaintext and accessible to anyone who got shell on Sterling's testing server.

This is not a problem confined to solo developers. It is a class of failure that scales upward because the same pressures exist at every level: fast shipping, missing training, no pre-commit scanner, no secret-management platform, no review culture.

### Factor 6 — no culture of breach notification

The Nigeria Data Protection Act of 2023 mandates breach notification within 72 hours of awareness. In practice, for every breach we can verify from public sources over the past 12 months:

- Sterling Bank: silent after NDPC served Notice of Investigation
- Remita: silent
- Corporate Affairs Commission: 14-plus day delay, vague statement, no formal notification
- MTN Nigeria: claimed unaffected by MTN Group's breach; credibility unclear
- Globacom 2023: minimal public acknowledgement

The pattern is an institutional instinct to minimize publicly, negotiate privately, and notify customers only when the news breaks elsewhere. This is a compliance failure. It is also a trust failure. And it creates a secondary market gap — Nigerian consumers typically learn they were breached from the media, not from the entity that lost their data.

---

## Part 3 — who is most exposed right now

The NDPC enforcement cascade has moved sector-by-sector through 2024 and 2025: banking, education, payments. Each sector got a wave of regulatory scrutiny, some high-profile enforcement actions, and a period of reactive cleanup. The cascade has not stopped moving. Based on the signal pattern — regulatory announcements, parallel-regulator moves like the NCC's February 13, 2026 telecom breach-notification directive, and the natural logic of "where do the worst structural weaknesses intersect with the largest exposed populations" — the next three sectors are identifiable.

**Telecom.** Four major operators (MTN, Airtel, Globacom, 9mobile) plus smaller MVNOs. Tens of millions of subscriber records. Location data. Payment credentials tied to airtime purchases and mobile-money flows. The NCC has already tightened reporting rules to 48 hours. MTN Group's Q2 2025 breach is a precedent. The first telecom-class breach in Nigeria post-NCC rule is likely within the next 6 months.

**Healthcare.** The National Health Insurance Scheme (NHIS), private HMOs (Reliance HMO, AXA Mansard, Avon), digital-health fintechs (Helium Health, 54gene, Ankoma, Sevilla), private-hospital IT departments. Africa-wide healthcare is averaging 3,575 weekly attacks per 2025 data — a 38 percent year-over-year increase. Nigerian private healthcare is the most-targeted sector on the continent. M-Tiba in Kenya was breached in late 2025. The Nigerian analog is overdue.

**E-commerce.** Jumia, Konga, Jiji, plus newer vertical plays (Chowdeck, Sendme, Patricia, Rida). High PII volume. Weak pre-existing baseline. Most run on older LAMP or Magento stacks that check every box on the factor-1 legacy-tier profile. A CAC-style sequential-ID breach in this sector is a straightforward attack.

If your organization is in one of these three sectors and you score three or more on the six-factor signature, you are not wondering whether a Sterling-class incident will happen to you. You are waiting for the specific attacker who decides you are the easiest target this week.

---

## Part 4 — what to do right now

Concrete, non-vendor-specific, in the order that each control has the highest leverage per hour of effort:

**One — inventory every subdomain.** Run a passive DNS enumeration across every domain your organization owns. The tools are free. The output is a list. You are specifically looking for subdomains that are live, fingerprinted to a legacy stack, and not in your current maintenance inventory. These are the Sterling testing servers. Take them offline or re-owner them to a team that has the authority to patch.

**Two — add HSTS and basic headers on every customer-facing host.** One line of nginx config per host. One line of Cloudflare Transform Rule if you are on a CDN. Hours of work for one engineer. Nothing to lose, basic protection gained, a demonstrable compliance signal for NDPC.

**Three — scan every public repository owned by employees and contractors.** Every major secret scanner (GitGuardian, TruffleHog, Gitleaks) is free or low-cost. Run it across every repository owned by anyone who has ever worked for you, and every repository where an `.env.production` file has shown up in any branch at any time. Rotate every credential that appears. Configure pre-commit hooks so new credentials can never land in source control again.

**Four — audit your third-party vendor credentials and move them out of repositories.** Every API key, every service account, every OAuth client secret used to integrate with a third party — if any of it lives in a code repository (public or private) in plaintext, move it immediately. The canonical destinations are encrypted environment variable systems (Vercel, Netlify, Fly, Railway, Render for hosted apps), a secrets vault (HashiCorp Vault, Doppler, Infisical, AWS Secrets Manager), or at minimum encrypted-at-rest files outside the repo. The Sterling-to-Remita pivot happened because Remita credentials were in a Sterling repo in plaintext. That exact failure is the one most worth removing.

**Five — build a breach-notification process BEFORE you need one.** Define who calls whom in the first 30 minutes. Draft the NDPC notification letter template. Draft the customer notification email. Decide in advance what gets said, by whom, and in what sequence. The 72-hour clock is not enough time to invent a process under stress. The Sterling silence was not malicious — it was an absence of a pre-built process.

---

## Part 5 — where Securva fits

Securva is an independent security research project based in Calgary and Lagos. Our work is organized around three lines:

**External attack-surface mapping.** We scan Nigerian enterprises the same way an attacker would. We do not exploit. We do not pivot. We produce a report that lists exactly what an outsider can see about your infrastructure. If you want one for your organization — or you want to see the public Phase 1 and Phase 2 samples we have already published — you can reach us at hello@securva.net.

**Coordinated credential-leak disclosure.** Our scanner continuously watches GitHub for new commits of Nigerian-payment, Nigerian-telecom, Nigerian-fintech, Web3, and vendor-specific credentials. When we find leaked credentials, we notify the owner under coordinated disclosure — 14-day window, no publication, no media, no monetization of the finding itself. We have disclosed to Flutterwave, Esusu, three Supabase-using Web3 operators, trustbank.tech, and several smaller operators. Every one of these disclosures ended in rotation within hours of the letter landing.

**Public research + content.** This post is one. The Phase 1 introductory post on our blog is another. We publish the pattern, never the target. The purpose is to shift the collective baseline of what "acceptable security posture" means in the Nigerian market. If the bar rises, the Sterling-class breach rate falls. We are not going to fix this sector by yelling at individual CTOs. We can possibly fix it by making the signature so public and so recognizable that skipping the basics stops being socially acceptable inside engineering leadership.

Our core product — Securva Snapshot — is the external attack-surface report, priced to be accessible to Nigerian SMEs. First three customers get the snapshot at a discounted rate for case-study permission. After that, standard pricing. We are partnering with a limited number of compliance-forward organizations in the telecom, healthcare, and e-commerce sectors to run pre-emptive snapshots before the NDPC reaches their sector. If that describes your organization and you would like to be in the batch, get in touch.

---

## The bottom line

Sterling Bank was not breached by a nation-state. It was breached by a single human being using a three-month-old CVE and a credentials-in-a-repo antipattern that every junior engineer on your team knows is wrong.

Remita was not breached at all in the technical sense. It was collateral from Sterling's operational hygiene.

CAC was not breached by clever exploitation. It was enumerated — because someone, at some point, decided sequential integer user IDs were good enough.

All three of these failures are structural, not technical. The controls are known. The tools are free. The only missing ingredient is the attention.

Every Nigerian CTO and security lead reading this has about six months. The NDPC has told you, indirectly, where the enforcement cascade is going next. The attacker community does not need a hint — the targets are obvious. The question is whether your organization is going to be the one that ran the scan and patched the gaps before the notice arrived, or the one that is written about in the next post like this one.

We hope it is the former. If we can help, the inbox is open.

---

*Contact: hello@securva.net — we respond within 24 hours, and a brief reply is always free.*

*Methodology note: all data cited in this post comes from public sources (NDPC announcements, journalistic reporting by Technext24 / Guardian Nigeria / Punch / Businessday NG / The Record / SecurityWeek) or from Securva's own Phase 1 and Phase 2 infrastructure mapping research. No private data, no proprietary leaks, no credential values are referenced. Links to sources on request at hello@securva.net.*
