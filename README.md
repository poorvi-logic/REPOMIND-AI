RepoMind AI

Intelligent Repository Understanding & Investigation Platform

RepoMind AI is an AI-powered developer platform designed to help developers understand, explore and investigate unfamiliar software repositories.

It analyses source code, identifies functions and classes, maps dependencies, detects potential code-quality and security risks, and provides context-aware explanations through an AI assistant.

It also includes MCP integration, Jira connectivity and CodeQuest, an interactive learning environment generated from actual repository analysis.

Problem Statement

Understanding an unfamiliar codebase can be time-consuming. Developers often need to identify where functionality is implemented, trace dependencies, understand execution flow and investigate potential issues.

Traditional text search provides limited context, while AI-generated explanations can sometimes contain inaccurate information.

RepoMind addresses this by combining structural code analysis with source-grounded AI assistance, helping developers explore code with relevant file and line references.

Key Features

1. Repository Analysis

* Upload ZIP repositories.
* Analyse public GitHub repositories.
* Extract Python source structures.
* Identify functions, classes, methods and imports.
* Generate searchable repository indexes.

2. AST-Based Code Intelligence

* Python AST-based extraction.
* Function and class identification.
* Function call relationships.
* Import and dependency analysis.
* Cyclomatic complexity analysis.
* Source references with line numbers.

3. Repository Explorer

* Browse repository files.
* Search filenames, functions and classes.
* Search source code and imports.
* View syntax-highlighted code.
* Explore source references.

4. Dependency Intelligence

* Module dependency graphs.
* Function call graphs.
* Import cycle detection.
* Incoming and outgoing relationships.
* Confidence labels for detected relationships.

5. Risk Analysis

Detect potential issues such as:

* Hardcoded credentials.
* Unsafe subprocess execution.
* Dynamic code execution.
* Unsafe deserialization.
* Risky SQL construction.
* Excessive function complexity.
* Duplicate function bodies.
* Potentially unused functions.

Findings include severity, source evidence, explanations and suggested remediation.

6. AI Assistant and RAG

* Repository-grounded question answering.
* Beginner, Developer and Deep Dive explanation modes.
* Follow-up conversations.
* Streaming responses.
* Source citations with file paths and line numbers.
* Optional OpenAI integration.
* Deterministic fallback when an API key is unavailable.

7. CodeQuest — Learn Your Codebase

An interactive educational feature that helps developers understand an unfamiliar repository through six learning modes:

* Architecture Detective
* Function Detective
* Workflow Challenge
* Bug Detective
* Dependency Challenge
* Risk Detective

Includes difficulty levels, hints, explanations, evidence references, progress tracking and answer review.

Questions are generated using actual repository analysis rather than fixed project-specific examples.

8. MCP Integration

A Python MCP server exposing eight tools:

* scan_repository
* search_repository
* get_function_details
* get_dependency_map
* analyze_repository_risks
* explain_code
* ask_repository_question
* prepare_jira_ticket

Designed to make repository intelligence accessible to compatible AI clients.

9. Jira Integration

* Jira connection validation.
* Finding-to-ticket conversion.
* Ticket preview.
* Explicit confirmation before creation.
* Issue status and creation history.

10. Dashboard and Reports

* Repository statistics.
* Source-file coverage.
* Function and class counts.
* Dependency information.
* Risk summaries.
* Complexity insights.
* JSON report export.

Technology Stack

Component	Technologies
Backend	Python, FastAPI, Pydantic
Frontend	React, TypeScript, Vite
Code Analysis	Python AST
AI	OpenAI API
Retrieval	BM25, NumPy, RAG
MCP	Python MCP SDK
Database	SQLite
Integration	Jira Cloud REST API
Testing	Pytest
Visualisation	React Flow, Dagre

Architecture

                 React + TypeScript
                         |
                         v
                   FastAPI Backend
                         |
                   AppServices
                         |
       +-----------------+-----------------+
       |                 |                 |
       v                 v                 v
  AST Analysis     AI Intelligence    MCP Server
       |                 |                 |
       v                 v                 v
 Dependency Maps      RAG / LLM       MCP Tools
       |
       v
  Risk Analysis
       |
       v
  Repository Index
       |
       v
   SQLite Storage
Additional integrations:
CodeQuest | Jira Cloud | JSON Reports

Project Structure

RepoMind_AI/
│
├── app/
│   ├── api/
│   ├── learning/
│   ├── main.py
│   ├── extractor.py
│   ├── dependencies.py
│   ├── risks.py
│   ├── intelligence.py
│   ├── retrieval.py
│   ├── mcp_server.py
│   ├── mcp_tools.py
│   ├── jira.py
│   └── services.py
│
├── frontend/
│   ├── src/
│   ├── package.json
│   └── package-lock.json
│
├── sample_project/
├── tests/
├── docs/
├── requirements.txt
├── pytest.ini
├── .env.example
├── .gitignore
└── README.md

Installation

Prerequisites

* Python 3.10+
* Node.js 20+
* Git

Backend Setup

python -m venv .venv

Windows PowerShell:

.venv\Scripts\Activate.ps1

Install dependencies:

pip install -r requirements.txt

Create the environment file:

copy .env.example .env

Frontend Setup

cd frontend
npm install
npm run build
cd ..

Run the Application

From the project root:

uvicorn app.main:app --reload

Open:

http://127.0.0.1:8000

Configuration

Optional integrations can be configured through .env.

Important variables include:

OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
JIRA_BASE_URL=
JIRA_EMAIL=
JIRA_API_TOKEN=
RETRIEVAL_MODE=lexical
MAX_UPLOAD_MB=500

Never commit real API keys, passwords or credentials.

Testing

Run backend tests:

pytest

Check frontend types:

cd frontend
npm run typecheck

Build the frontend:

npm run build

Current Scope and Limitations

* Python is the currently supported language for AST-based analysis.
* Other file types are counted but not structurally analysed.
* OpenAI-powered features require API credentials.
* Jira functionality requires a configured Jira Cloud account.
* Some advanced analysis features remain under development.
* AI and external service integrations should be evaluated against their actual configuration and availability.

See docs/FEATURE_STATUS.md and docs/REQUIREMENTS_CHECKLIST.md for implementation status and known limitations.

Project Goal

RepoMind aims to make complex software repositories easier to understand by combining code intelligence, AI-assisted explanations, dependency analysis and interactive developer learning.

Built to help developers understand not just what code exists, but how it works and how its components connect.