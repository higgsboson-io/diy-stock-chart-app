# Reverse Engineering & Design Documentation — Prompt Guide

> A reference for using AI-assisted code analysis to produce professional software design documents from an existing codebase.

---

## 🎯 The Prompt

```
You are a Senior Software Architect performing a reverse engineering review.

## Context
- Project: @[diy-sock-chart-app] — a Python desktop application
- Existing docs: @[diy-sock-chart-app/chart-app/algorithm.md]

## Task
Perform a comprehensive code review and produce the following deliverables:

### 1. Software Design Document (`design.md`)
Create `design.md` in the project root (same directory as `readme.md`) containing:

**High-Level Design (HLD):**
- System overview and key design principles
- Component architecture diagram
- Threading & concurrency model
- Data flow sequence diagrams (startup, data acquisition)
- Technology stack summary

**Low-Level Design (LLD):**
- Class diagram with attributes, methods, and relationships
- Module-by-module method breakdown tables
- State management model
- Caching & persistence strategy (file layout, naming conventions, TTL)
- Rendering pipeline activity diagram
- Key interaction flows (window change, resampling, crosshair)

**Data Model:**
- Entity-Relationship Diagram for all persisted artifacts

**Cross-Cutting Concerns:**
- Logging, error handling, DPI awareness, performance considerations

**Diagram Requirements:**
- All diagrams must be in **PlantUML** format (```plantuml code blocks)
- Diagrams must reflect the actual codebase — no placeholders or assumptions
- Use proper PlantUML skinparams for clean rendering

**Table Drawing Requirements:**
- Use proper Markdown table syntax for clean rendering
- Tables must be aligned even in plain text view

### 2. Algorithm Document Review (`algorithm.md`)
- Cross-reference every algorithm description against the actual source code
- Fix any inaccuracies (e.g., incorrect intervals, outdated logic, missing features)
- Add cross-reference links to the new design document

### 3. README Updates (`readme.md`)
- Add navigation links to both `design.md` and `algorithm.md` in the introduction section

## Constraints
- Read ALL source files before writing any documentation
- Every diagram and table must be traceable to actual code — no hallucination
- Use consistent terminology matching the codebase (class names, method names, variable names)
```

---

## 💡 Prompt Engineering Techniques Used

| Technique                            | Where Applied                                                                                                      |
|:-------------------------------------|:-------------------------------------------------------------------------------------------------------------------|
| **Role Assignment**                  | `"You are a Senior Software Architect"` — frames the AI's expertise level and output quality                       |
| **Structured Output Specification**  | Numbered deliverables with nested bullet hierarchies — removes ambiguity on what to produce                        |
| **@ Mentions (Context Anchoring)**   | `@[diy-sock-chart-app]` and `@[algorithm.md]` — gives the AI direct file/folder handles to work with               |
| **Explicit Constraints**             | The `## Constraints` section prevents common failure modes (hallucinated diagrams, partial code review)            |
| **Format Directives**                | `"PlantUML format"`, `"method breakdown tables"` — specifies the exact output format so you don't get Mermaid      |
| **Negative Instructions**            | `"no placeholders or assumptions"`, `"no hallucination"` — guardrails against low-quality output                   |
| **Traceability Requirement**         | `"traceable to actual code"` — forces the AI to ground every claim in source                                       |
| **Scope Control**                    | Separating HLD vs LLD vs Data Model — prevents the AI from blending abstraction levels                             |

---

## 📋 Boilerplate Setup

Before running the prompt, make sure:

1. **VS Code Extension**: Install the **PlantUML** extension (`jebbs.plantuml`)
2. **PlantUML Server**: Add to `.vscode/settings.json`:
   ```json
   {
       "plantuml.server": "https://www.plantuml.com/plantuml",
       "plantuml.render": "PlantUMLServer"
   }
   ```
3. **Preview**: Place cursor inside any `@startuml...@enduml` block → press **Alt+D**
