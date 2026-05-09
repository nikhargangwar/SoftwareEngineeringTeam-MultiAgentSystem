# AI Software Engineering Team

A multi-agent system that reads a GitHub issue, understands it, makes code changes, writes tests, commits to a branch, and opens a pull request autonomously.

Deployed Link-  https://ai-swe-team-console-5doq.onrender.com/
## Project Overview

This repository contains an automated Software Engineering team built as a collection of cooperating AI agents. The system is designed to take a GitHub issue, analyze its intent, locate the relevant source files, generate a fix, self-review the change, create tests, and publish the result back to GitHub.

## Core Components

- `SoftwareEngineerTeam.py` - The main orchestrator and agent implementations.
- `backend_api.py` - FastAPI server exposing the AI team workflow as an HTTP API with real-time event streaming.
- `frontend/` - Angular UI for running the system and watching progress.
- `.env` - Local configuration for GitHub and Gemini credentials.
- `requirements.txt` - Python dependencies.

## System Workflow

The pipeline is composed of 11 agents, each responsible for a distinct phase of the fix process:

1. **Issue Reader Agent**
   - Reads the GitHub issue, its labels, and comments using the GitHub API.
   - Collects issue metadata needed by all downstream agents.

2. **Issue Analyzer Agent**
   - Uses Google Gemini to classify issue type, severity, root cause, affected areas, and suggested approach.
   - Produces structured JSON that guides the rest of the workflow.

3. **Repo Explorer Agent**
   - Inspects the repository tree and identifies candidate source files.
   - Builds a map of the codebase to support targeted file selection.

4. **File Locator Agent**
   - Ranks the files most likely to be involved in the fix by comparing issue analysis results against repository contents.

5. **Code Reader Agent**
   - Loads the contents of the selected files so the AI can reason with actual source code.

6. **Solution Designer Agent**
   - Designs the implementation plan before code changes are made.
   - Outputs the change strategy, risk level, and testing notes.

7. **Code Writer Agent**
   - Generates complete updated file contents for each affected file using the structured design.
   - Ensures every file returned is complete and ready to commit.

8. **Code Reviewer Agent**
   - Performs a self-review of the generated code.
   - Approves or corrects the code to reduce mistakes before committing.

9. **Test Writer Agent**
   - Generates unit tests for the changes, increasing confidence and quality.
   - Supports Python and can be extended for JavaScript/TypeScript.

10. **Git Commit Agent**
    - Uses the GitHub Git Data API to create a branch, build blobs/trees, commit the changes, and update the branch reference.
    - Produces a clean branch and commit history automatically.

11. **PR Creator Agent**
    - Creates a professional pull request on GitHub.
    - Adds a PR description, and comments on the original issue linking the PR.

## Technology Stack

- Python
- FastAPI for the backend API and event streaming
- Google Gemini via `google-generativeai`
- PyGithub for GitHub repository and pull request automation
- `python-dotenv` for secure local configuration
- Angular frontend served from `frontend/`
- GitHub Git Data API for branch/commit creation
- Server-Sent Events (SSE) for live progress streaming in the UI

## Architecture & Concepts

- **Multi-Agent Orchestration**: Each step is isolated as an agent with one clear responsibility.
- **Prompt Engineering**: Agents use custom system prompts and structured JSON output requirements to reduce hallucinations.
- **Self-Review Loop**: The Code Reviewer Agent checks and corrects generated code before it is committed.
- **Automated GitOps**: The system automates branch creation, commit generation, and pull request creation.
- **Safety**: Structured JSON and explicit instructions help ensure the AI returns predictable, parseable output.
- **Modular Design**: The orchestrator `run_swe_team()` can be extended with new agents, policies, or additional validation.

## Setup

1. Create and activate a Python environment.
2. Install the dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file with the following variables:

```dotenv
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
GITHUB_REPO=yourusername/your-repo-name
GEMINI_API_KEY=AIzaSy-xxxxxxxxxxxxxxxxxxxx
```

> Keep `.env` out of version control. Do not commit tokens or API keys.

## Running the System

### Run from the command line

```bash
python SoftwareEngineerTeam.py
```

This will execute the full pipeline for the issue ID configured in the entry point.

### Run the API backend

```bash
uvicorn backend_api:app --reload
```

Then open the Angular frontend or call the API endpoints to start runs and stream progress.

## API Endpoints

- `GET /api/stages` - Returns the list of workflow stages.
- `POST /api/runs` - Starts a new issue fix workflow with `repo` and `issue_id`.
- `GET /api/runs/{run_id}` - Checks run status and summary.
- `GET /api/runs/{run_id}/events` - Streams live log and stage updates.

## Customization

- Update the issue ID in `SoftwareEngineerTeam.py` or invoke `run_swe_team(issue_number, repo_full_name)` programmatically.
- Adjust prompts, agent decisions, or file selection heuristics in `SoftwareEngineerTeam.py`.
- Extend the frontend to support additional controls or telemetry.

## Notes

- The system is designed for experimentation and proof-of-concept automation.
- Real-world use should include stronger validation, unit test execution, security reviews, and access controls.
- The current implementation depends on Gemini and GitHub API credentials.

## License

Use this project as a reference implementation for AI-assisted software engineering workflows.
