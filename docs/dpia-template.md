# DPIA Template — Jean Field Observer

> ⚠️ **DISCLAIMER: This is a template only. It does not constitute legal advice.
> Before any deployment involving employee data, a qualified Data Protection Officer (DPO)
> must review and validate this document. Consult your legal counsel and DPO.**

---

## 1. Processing Identity

| Field | Value |
|-------|-------|
| **Controller** | [Organisation name] |
| **DPO** | [DPO name and contact] |
| **Processing name** | Jean — business process field observation |
| **Version** | 1.0 |
| **Date** | [Date] |
| **Review date** | [Date + 1 year] |

---

## 2. Processing Purpose and Legal Basis (Art. 6 GDPR)

### Purpose
Jean captures structural transitions between business applications (e.g. Excel → SAP → Submit)
to detect undocumented process variants and improve organisational knowledge documentation.

**Jean does NOT capture:**
- Window titles, document names, or file paths
- Keystrokes or continuous screen data
- Personal communications (email content, chat)
- Employee identity (workstation IDs are pseudonymous UUIDs)

### Legal Basis

| Basis | Article | Applicable? |
|-------|---------|-------------|
| Legitimate interest (process improvement) | Art. 6(1)(f) | ✅ Candidate — requires LIA |
| Performance of a contract (employment) | Art. 6(1)(b) | ⚠️ Requires employment contract clause |
| Consent | Art. 6(1)(a) | ⚠️ Freely given consent is difficult in employment context |

**Recommended basis:** Legitimate Interest, subject to a Legitimate Interest Assessment (LIA)
documenting that the processing does not override employee fundamental rights.

> 📌 **Action required:** Complete a LIA before deployment.

---

## 3. Categories of Personal Data and Minimisation

### Data Collected

| Field | Category | Minimisation measure |
|-------|----------|---------------------|
| `workstation_id` | Pseudonymous identifier (UUID) | Not linked to employee name without a separate key |
| `app` | Application name only (e.g. "SAP") | Window title, document name excluded |
| `event_type` | Structural action type (APP_FOCUS, SAVE, SUBMIT…) | No content captured |
| `timestamp` | Event time | Retained at second precision only |
| `process_context` | Business process label (e.g. "invoice-exception") | Set by administrator, not auto-inferred from content |
| `session_id` | Pseudonymous session UUID | Not linked to employee without key |

### Data NOT Collected (by design)
- Employee names, usernames, or email addresses
- Document content, file names, or URLs
- Keystrokes or clipboard content
- Screen recordings or screenshots
- Personal health, financial, or communication data

### Pseudonymisation Key
The mapping `workstation_id → employee` is held separately and must be:
- Stored with access controls limiting access to DPO and authorised managers
- Never stored in the same database as Jean events
- Deleted when the employee leaves the organisation

---

## 4. Data Subject Rights and Retention

### Rights (GDPR Chapter III)

| Right | Jean mechanism |
|-------|---------------|
| Right to information (Art. 13/14) | Consent notice distributed before deployment |
| Right of access (Art. 15) | DPO queries `jean-aggregator` by workstation_id |
| Right to erasure (Art. 17) | Events deleted from DB by workstation_id |
| Right to object (Art. 21) | Employee notifies manager; workstation excluded from capture |
| Right to restriction (Art. 18) | Aggregation paused for the workstation |
| Portability (Art. 20) | JSON export of events by workstation_id |

> 📌 **Action required:** Implement a `/privacy/erase?workstation_id=X` endpoint
> (not yet in Jean MVP) before production deployment with identified employees.

### Retention Period

| Data type | Retention | Justification |
|-----------|-----------|---------------|
| Raw events (aggregator) | 90 days | Pattern detection requires a rolling window; no longer needed after |
| Session traces | 90 days | Same window as events |
| Pattern hypotheses | 12 months | Required for trend analysis |
| Validated FieldObservations | Indefinite | Corpus knowledge asset; no longer linked to individuals after validation |
| Pseudonymisation key | Duration of employment + 1 year | HR standard |

> 📌 **Action required:** Implement automated retention enforcement (not yet in MVP).

---

## 5. Risk Assessment

### Risk Matrix

| Risk | Likelihood | Severity | Score | Mitigation |
|------|-----------|----------|-------|------------|
| Re-identification of employee from workstation_id | Medium | High | **High** | Keep pseudonymisation key separate; DPO access only |
| Covert surveillance perception (chilling effect) | High | Medium | **High** | Transparent communication; consent notice; works council consultation |
| Data breach (aggregator exposed) | Medium | High | **High** | API key auth (JEAN_API_KEY), TLS in production, no public endpoint |
| Function creep (supervisor uses data for performance review) | Medium | High | **High** | Policy: data used only for process documentation; no HR access |
| Excessive retention | Low | Medium | **Medium** | Implement 90-day auto-purge before production |
| Data transferred outside EU | Low | High | **High** | Deploy on EU infrastructure; document transfer basis if SaaS |

### Overall Risk Before Mitigation: **HIGH**
### Overall Risk After Mitigation: **MEDIUM** (conditional on all actions completed)

---

## 6. Safeguards

- [ ] API key authentication (`JEAN_API_KEY`) enabled on all non-public endpoints
- [ ] TLS (HTTPS) enforced for all network communication
- [ ] Aggregator not exposed to the public internet (firewall / VPN)
- [ ] Pseudonymisation key stored in a separate, access-controlled system
- [ ] Employee information notice distributed before any data collection
- [ ] Works council / employee representatives consulted (if required by national law)
- [ ] DPO appointed and consulted on this DPIA
- [ ] 90-day retention enforcement implemented
- [ ] Privacy erasure endpoint implemented and tested
- [ ] Incident response procedure documented

### Residual Risk
After all safeguards are implemented, residual risk is assessed as **MEDIUM** due to the
inherent difficulty of fully eliminating re-identification risk in workplace monitoring contexts.

**DPO recommendation required** before proceeding to production with more than 50 employees.

---

## 7. Consultation and Approval

| Role | Name | Date | Signature |
|------|------|------|-----------|
| DPO | | | |
| Legal Counsel | | | |
| Works Council / CSE | | | |
| CISO | | | |
| Project Owner | | | |

---

## 8. References

- GDPR (EU) 2016/679, Articles 5, 6, 13, 35
- CNIL guidelines on employee monitoring (updated 2023)
- CNIL sanction — continuous employee monitoring (February 4, 2025, €40k)
- EDPB Guidelines 01/2022 on data subject rights
- Jean VISION.md — legal design rationale
