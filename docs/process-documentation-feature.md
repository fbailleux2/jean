# Jean — Process Documentation Feature
# Jean — Fonctionnalité de Documentation des Processus

> **Version:** 1.0.0 — `feat/process-documentation-v1`
> **Branch / Branche:** `feat/process-documentation-v1`
> **Tests:** 275 passing / 275 tests passants

---

## English

### Overview

This feature transforms Jean from a passive field observer into a complete **process documentation engine**. It implements the 10-step methodology for capturing real business processes — not what the procedures say, but what actually happens — and makes them machine-readable for AI automation.

> "Without a clear process → AI is useless. With a clear process → AI is ultra-efficient."

### Architecture — 5 Phases

```
Phase 1 ─── Enriched Capture
             Clipboard detection, tool-switch friction, ERP search misses

Phase 2 ─── Irritants & Implicit Decisions
             Auto-detection of friction, operator hotkey flagging, decision annotations

Phase 3 ─── Process Modeling
             ProcessDefinition, ProcessStep, Input/Output modeling, REST CRUD API

Phase 4 ─── Documentation & Business Rules
             Markdown/JSON export, if/then rule extraction from annotations and patterns

Phase 5 ─── Continuous Improvement
             Drift detection, gain metrics (before/after), version history
```

---

### Phase 1 — Enriched Capture

#### New EventTypes

| Type | Trigger | Privacy |
|------|---------|---------|
| `CLIPBOARD_COPY` | Ctrl+C detected | App name only — content never captured |
| `CLIPBOARD_PASTE` | Ctrl+V detected | App name + whether it is cross-app |
| `TOOL_SWITCH` | Same app pair repeated ≥ 3 times OR cross-app paste | App names only |
| `IRRITANT` | Ctrl+Alt+I hotkey (operator) | App name only |

#### Cross-app paste detection

When an operator copies in App-A and pastes in App-B, Jean emits a `TOOL_SWITCH` event — this is the "copy-paste between tools" friction the methodology asks to track.

```python
# Automatically detected — no configuration required
# copy in Outlook → paste in SAP → TOOL_SWITCH emitted
```

#### ERP Search Miss

New endpoint `POST /connectors/erp/searches` captures failed lookups and retries:

```json
{
  "session_id": "sess-001",
  "process_context": "invoice-exception",
  "search": {
    "search_term_hash": "sha256:...",
    "entity_type": "customer",
    "result_count": 0,
    "attempt_number": 2
  }
}
```

The raw search term is **never ingested** — only its hash and outcome metadata.

#### New Models

```python
ToolTransition(from_app, to_app, transition_count, is_cross_app_paste)
IrritantSignal(source, irritant_type, app, related_event_ids)
```

---

### Phase 2 — Irritants & Implicit Decisions

#### Automatic Irritant Detection (`IrritantDetector`)

The aggregator runs `IrritantDetector` on every `/ingest` batch:

| Detection type | Rule |
|----------------|------|
| `repeated_action` | Same `(app, event_type)` seen ≥ 5 times in one session |
| `tool_switch_friction` | `TOOL_SWITCH` event present (emitted by Phase 1) |
| `cross_app_paste` | ≥ 3 cross-app clipboard pastes in one session |

Thresholds are configurable: `IrritantDetector(repeat_threshold=5, clipboard_threshold=3)`.

#### Operator Hotkey

Press **Ctrl+Alt+I** at any moment to flag the current step as frustrating.
The active application is recorded — no content is captured.

#### Decision Annotations (`DecisionAnnotation`)

Captures implicit rules operators follow:

```python
DecisionAnnotation(
    text="si client VIP → priorité haute",
    condition="client VIP",        # auto-extracted
    action="priorité haute",       # auto-extracted
    app="SAP",
    related_event_id="evt-123",
)
```

---

### Phase 3 — Process Modeling

#### ProcessDefinition

Declares a business process that Jean will observe and document:

```python
ProcessDefinition(
    name="invoice-exception-handling",
    process_context="invoice-exception",
    trigger="incoming email from client with PDF attachment",
    inputs=[
        ProcessInput(name="client_email", source="email"),
        ProcessInput(name="invoice_pdf", source="file"),
    ],
    outputs=[
        ProcessOutput(name="validated_order", destination="erp"),
    ],
    steps=[
        ProcessStep(sequence=1, action="Read email", tool="Outlook",
                    decision="check completeness", irritant_score=0.2),
        ProcessStep(sequence=2, action="Search customer", tool="SAP",
                    decision="variable spelling → retry", irritant_score=0.8),
        ProcessStep(sequence=3, action="Create customer if absent", tool="SAP",
                    irritant_score=0.6),
        ProcessStep(sequence=4, action="Enter order", tool="SAP",
                    decision="check stock", irritant_score=0.4),
    ],
)
```

#### REST API (mounted at `/process-mapper`)

| Method | Route | Description |
|--------|-------|-------------|
| `POST` | `/process-mapper/processes` | Declare a process |
| `GET` | `/process-mapper/processes` | List all processes |
| `GET` | `/process-mapper/processes/{id}` | Get one process |
| `PUT` | `/process-mapper/processes/{id}` | Update (bumps minor version) |
| `DELETE` | `/process-mapper/processes/{id}` | Remove |
| `GET` | `/process-mapper/processes/{id}/history` | Version history |
| `GET` | `/process-mapper/processes/{id}/drift` | Drift report vs. reality |

---

### Phase 4 — Documentation & Business Rules

#### Markdown Export

```bash
GET /process-mapper/{process_id}/export/markdown
```

Generates the table format from the methodology:

```markdown
# invoice-exception-handling

**Version:** 1.0.0
**Context:** `invoice-exception`

## Trigger

incoming email from client with PDF attachment

## Inputs

- **client_email** — source: `email` *(required)*

## Steps

| Étape | Action | Outil | Décision | Irritant |
|-------|--------|-------|----------|----------|
| 1 | Read email | Outlook | check completeness |  |
| 2 | Search customer | SAP | variable spelling → retry | ⚠ high |
| 3 | Create customer if absent | SAP | — | ~ medium |
| 4 | Enter order | SAP | check stock | ~ medium |
```

#### JSON Export (KFabric-compatible)

```bash
GET /process-mapper/{process_id}/export/json
```

Returns machine-readable format directly ingestable by KFabric.

#### Business Rule Extractor

Extracts structured `if/then` rules from:
1. **DecisionAnnotations** — operator-provided rules (confidence 0.7–0.9)
2. **PatternHypotheses** — recurring sequences that imply rules (confidence ≥ 0.6)

```python
# Input annotation text
"si client VIP → priorité haute"

# Output rule
{
    "source": "decision_annotation",
    "condition": "client VIP",
    "action": "priorité haute",
    "confidence": 0.7,
}
```

---

### Phase 5 — Continuous Improvement

#### Drift Detection

Compares declared process steps against recent SessionTraces using Jaccard distance:

```
drift_score = 1 - |declared_event_types ∩ observed_event_types|
                  ─────────────────────────────────────────────
                  |declared_event_types ∪ observed_event_types|
```

- `drift_score = 0.0` — reality matches declaration perfectly
- `drift_score = 1.0` — nothing observed matches what was declared
- `alert = True` when `drift_score > 0.5` (configurable)

```bash
GET /process-mapper/{process_id}/drift
# → { "drift_score": 0.33, "alert": false, ... }
```

#### Gain Metrics

Track improvements between two time periods:

```python
GainTracker().compute(
    process,
    traces_before=[...],  # before process update
    traces_after=[...],   # after process update
    period_start=datetime(...),
    period_end=datetime(...),
)
# → irritant_reduction_pct: 45.0, tool_switch_reduction_pct: 30.0
```

#### Version History

Every save of a `ProcessDefinition` is automatically recorded:

```bash
GET /process-mapper/{process_id}/history
# → [{ "version": "1.0.0", "changed_at": "...", "snapshot_steps_count": 4 }, ...]
```

---

### New Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JEAN_IRRITANT_REPEAT_THRESHOLD` | `5` | Repeated action count to flag as irritant |
| `JEAN_IRRITANT_CLIPBOARD_THRESHOLD` | `3` | Cross-app paste count to flag |
| `JEAN_DRIFT_ALERT_THRESHOLD` | `0.5` | Drift score above which alert fires |

---

### Privacy Guarantees (unchanged)

All new captures follow Jean's core privacy principles:
- Clipboard **content** is never captured — only app names and cross-app transfer detection
- Search terms are never stored — only SHA-256 hash + result count
- Irritant hotkey records the active app only — no content, no context
- All new payloads pass through the existing `Anonymizer` before storage

---

### Quick Reference — New Hotkeys

| Hotkey | Action |
|--------|--------|
| Ctrl+C | Captured as `CLIPBOARD_COPY` (app name only) |
| Ctrl+V | Captured as `CLIPBOARD_PASTE` (cross-app detection) |
| Ctrl+Alt+I | Flag current step as irritant (`IRRITANT` event) |
| Ctrl+S | `SAVE` (pre-existing) |
| Ctrl+P | `PRINT` (pre-existing) |
| Ctrl+Shift+E | `EXPORT` (pre-existing) |

---

---

## Français

### Vue d'ensemble

Cette fonctionnalité transforme Jean d'un observateur passif en un **moteur de documentation des processus** complet. Elle implémente la méthodologie en 10 étapes pour capturer les vrais processus métier — non pas ce que disent les procédures, mais ce qui se passe réellement — et les rend lisibles par machine pour l'automatisation IA.

> « Sans process clair → IA inutile. Avec process clair → IA ultra efficace. »

### Architecture — 5 Phases

```
Phase 1 ─── Capture enrichie
             Détection presse-papiers, friction inter-outils, ratés de recherche ERP

Phase 2 ─── Irritants & Décisions implicites
             Détection automatique des frictions, touche de marquage opérateur, annotations de décision

Phase 3 ─── Modélisation des processus
             ProcessDefinition, ProcessStep, modélisation Entrées/Sorties, API REST CRUD

Phase 4 ─── Documentation & Règles métier
             Export Markdown/JSON, extraction de règles si/alors depuis les annotations et patterns

Phase 5 ─── Amélioration continue
             Détection de dérive, métriques de gains (avant/après), historique des versions
```

---

### Phase 1 — Capture enrichie

#### Nouveaux types d'événements

| Type | Déclencheur | Confidentialité |
|------|-------------|-----------------|
| `CLIPBOARD_COPY` | Ctrl+C détecté | Nom de l'app uniquement — contenu jamais capturé |
| `CLIPBOARD_PASTE` | Ctrl+V détecté | Nom de l'app + détection inter-app |
| `TOOL_SWITCH` | Même paire d'apps répétée ≥ 3 fois OU collage inter-app | Noms des apps uniquement |
| `IRRITANT` | Touche Ctrl+Alt+I (opérateur) | Nom de l'app uniquement |

#### Détection de collage inter-application

Quand un opérateur copie dans App-A et colle dans App-B, Jean émet un événement `TOOL_SWITCH` — c'est le « copier-coller entre outils » que la méthodologie demande de traquer.

```python
# Détecté automatiquement — aucune configuration requise
# copie dans Outlook → colle dans SAP → TOOL_SWITCH émis
```

#### Recherche ERP ratée

Nouvel endpoint `POST /connectors/erp/searches` pour capturer les recherches infructueuses et les tentatives multiples :

```json
{
  "session_id": "sess-001",
  "process_context": "invoice-exception",
  "search": {
    "search_term_hash": "sha256:...",
    "entity_type": "customer",
    "result_count": 0,
    "attempt_number": 2
  }
}
```

Le terme de recherche brut n'est **jamais ingéré** — uniquement son hash et les métadonnées du résultat.

#### Nouveaux modèles

```python
ToolTransition(from_app, to_app, transition_count, is_cross_app_paste)
IrritantSignal(source, irritant_type, app, related_event_ids)
```

---

### Phase 2 — Irritants & Décisions implicites

#### Détection automatique des irritants (`IrritantDetector`)

L'agrégateur exécute `IrritantDetector` à chaque batch `/ingest` :

| Type de détection | Règle |
|-------------------|-------|
| `repeated_action` | Même `(app, event_type)` vu ≥ 5 fois dans une session |
| `tool_switch_friction` | Événement `TOOL_SWITCH` présent (émis par la Phase 1) |
| `cross_app_paste` | ≥ 3 collages inter-app dans une session |

Les seuils sont configurables : `IrritantDetector(repeat_threshold=5, clipboard_threshold=3)`.

#### Touche de raccourci opérateur

Appuyer sur **Ctrl+Alt+I** à tout moment pour signaler que l'étape courante est frustrante.
L'application active est enregistrée — aucun contenu n'est capturé.

#### Annotations de décision (`DecisionAnnotation`)

Capture les règles implicites que les opérateurs suivent :

```python
DecisionAnnotation(
    text="si client VIP → priorité haute",
    condition="client VIP",        # extrait automatiquement
    action="priorité haute",       # extrait automatiquement
    app="SAP",
    related_event_id="evt-123",
)
```

---

### Phase 3 — Modélisation des processus

#### ProcessDefinition

Déclare un processus métier que Jean va observer et documenter :

```python
ProcessDefinition(
    name="traitement-exception-facture",
    process_context="invoice-exception",
    trigger="email entrant du client avec pièce jointe PDF",
    inputs=[
        ProcessInput(name="email_client", source="email"),
        ProcessInput(name="facture_pdf", source="file"),
    ],
    outputs=[
        ProcessOutput(name="commande_validée", destination="erp"),
    ],
    steps=[
        ProcessStep(sequence=1, action="Lire l'email", tool="Outlook",
                    decision="vérifier complétude", irritant_score=0.2),
        ProcessStep(sequence=2, action="Chercher le client", tool="SAP",
                    decision="orthographe variable → réessai", irritant_score=0.8),
        ProcessStep(sequence=3, action="Créer le client si absent", tool="SAP",
                    irritant_score=0.6),
        ProcessStep(sequence=4, action="Saisir la commande", tool="SAP",
                    decision="vérifier le stock", irritant_score=0.4),
    ],
)
```

#### API REST (montée sur `/process-mapper`)

| Méthode | Route | Description |
|---------|-------|-------------|
| `POST` | `/process-mapper/processes` | Déclarer un processus |
| `GET` | `/process-mapper/processes` | Lister tous les processus |
| `GET` | `/process-mapper/processes/{id}` | Obtenir un processus |
| `PUT` | `/process-mapper/processes/{id}` | Mettre à jour (incrémente la version mineure) |
| `DELETE` | `/process-mapper/processes/{id}` | Supprimer |
| `GET` | `/process-mapper/processes/{id}/history` | Historique des versions |
| `GET` | `/process-mapper/processes/{id}/drift` | Rapport de dérive vs. réalité |

---

### Phase 4 — Documentation & Règles métier

#### Export Markdown

```bash
GET /process-mapper/{process_id}/export/markdown
```

Génère le format tableau de la méthodologie :

```markdown
# traitement-exception-facture

**Version:** 1.0.0
**Contexte:** `invoice-exception`

## Déclencheur

email entrant du client avec pièce jointe PDF

## Entrées

- **email_client** — source : `email` *(requis)*

## Étapes

| Étape | Action | Outil | Décision | Irritant |
|-------|--------|-------|----------|----------|
| 1 | Lire l'email | Outlook | vérifier complétude |  |
| 2 | Chercher le client | SAP | orthographe variable → réessai | ⚠ high |
| 3 | Créer le client si absent | SAP | — | ~ medium |
| 4 | Saisir la commande | SAP | vérifier le stock | ~ medium |
```

#### Export JSON (compatible KFabric)

```bash
GET /process-mapper/{process_id}/export/json
```

Retourne un format lisible par machine directement ingérable par KFabric.

#### Extracteur de règles métier

Extrait des règles structurées `si/alors` depuis :
1. Les **DecisionAnnotations** — règles fournies par l'opérateur (confiance 0,7–0,9)
2. Les **PatternHypotheses** — séquences récurrentes qui impliquent des règles (confiance ≥ 0,6)

```python
# Texte d'annotation en entrée
"si client VIP → priorité haute"

# Règle extraite
{
    "source": "decision_annotation",
    "condition": "client VIP",
    "action": "priorité haute",
    "confidence": 0.7,
}
```

---

### Phase 5 — Amélioration continue

#### Détection de dérive

Compare les étapes de processus déclarées avec les SessionTraces récentes via la distance de Jaccard :

```
score_dérive = 1 - |types_événements_déclarés ∩ types_événements_observés|
                   ────────────────────────────────────────────────────────
                   |types_événements_déclarés ∪ types_événements_observés|
```

- `score_dérive = 0.0` — la réalité correspond parfaitement à la déclaration
- `score_dérive = 1.0` — rien de ce qui est observé ne correspond à ce qui a été déclaré
- `alert = True` quand `score_dérive > 0.5` (configurable)

```bash
GET /process-mapper/{process_id}/drift
# → { "drift_score": 0.33, "alert": false, ... }
```

#### Métriques de gains

Mesure les améliorations entre deux périodes :

```python
GainTracker().compute(
    process,
    traces_before=[...],  # avant mise à jour du processus
    traces_after=[...],   # après mise à jour du processus
    period_start=datetime(...),
    period_end=datetime(...),
)
# → irritant_reduction_pct: 45.0, tool_switch_reduction_pct: 30.0
```

#### Historique des versions

Chaque sauvegarde d'un `ProcessDefinition` est automatiquement enregistrée :

```bash
GET /process-mapper/{process_id}/history
# → [{ "version": "1.0.0", "changed_at": "...", "snapshot_steps_count": 4 }, ...]
```

---

### Nouvelles variables d'environnement

| Variable | Défaut | Description |
|----------|--------|-------------|
| `JEAN_IRRITANT_REPEAT_THRESHOLD` | `5` | Nombre de répétitions pour signaler un irritant |
| `JEAN_IRRITANT_CLIPBOARD_THRESHOLD` | `3` | Nombre de collages inter-app pour signaler |
| `JEAN_DRIFT_ALERT_THRESHOLD` | `0.5` | Score de dérive déclenchant une alerte |

---

### Garanties de confidentialité (inchangées)

Toutes les nouvelles captures respectent les principes fondamentaux de Jean :
- Le **contenu** du presse-papiers n'est jamais capturé — uniquement les noms des apps et la détection inter-app
- Les termes de recherche ne sont jamais stockés — uniquement leur hash SHA-256 + nombre de résultats
- La touche de raccourci irritant enregistre uniquement l'app active — aucun contenu, aucun contexte
- Tous les nouveaux payloads passent par l'`Anonymizer` existant avant stockage

---

### Référence rapide — Nouveaux raccourcis clavier

| Raccourci | Action |
|-----------|--------|
| Ctrl+C | Capturé comme `CLIPBOARD_COPY` (nom de l'app uniquement) |
| Ctrl+V | Capturé comme `CLIPBOARD_PASTE` (détection inter-app) |
| Ctrl+Alt+I | Signaler l'étape courante comme irritant (événement `IRRITANT`) |
| Ctrl+S | `SAVE` (pré-existant) |
| Ctrl+P | `PRINT` (pré-existant) |
| Ctrl+Shift+E | `EXPORT` (pré-existant) |

---

### Correspondance avec la méthodologie

| Étape de la méthodologie | Implémentée dans Jean |
|--------------------------|----------------------|
| 1. Partir du réel | ✅ Capture événementielle (pré-existant) |
| 2. Décomposer en micro-étapes | ✅ Phase 1 — clipboard + transitions + ERP search |
| 3. Identifier les décisions cachées | ✅ Phase 2 — DecisionAnnotation + extraction si/alors |
| 4. Cartographier les irritants | ✅ Phase 2 — IrritantDetector + IrritantCapture |
| 5. Identifier les entrées/sorties | ✅ Phase 3 — ProcessInput / ProcessOutput |
| 6. Lister les outils utilisés | ✅ Phase 1 — AppTransitionCapture + ToolTransition |
| 7. Formaliser simplement | ✅ Phase 4 — export Markdown tableau Step\|Action\|Tool\|Decision\|Irritant |
| 8. Valider avec le terrain | ✅ Phase 3+4 — jean-validator + workflow d'approbation |
| 9. Version exploitable IA | ✅ Phase 4 — export JSON + règles métier structurées → KFabric |
| 10. Boucle d'amélioration continue | ✅ Phase 5 — dérive, métriques de gains, historique des versions |

---

*Jean — 2026 — [github.com/fbailleux2/jean](https://github.com/fbailleux2/jean)*
