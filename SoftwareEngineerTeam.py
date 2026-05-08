# ================================================================
# AI SOFTWARE ENGINEERING TEAM
# A multi-agent system that reads a GitHub issue and autonomously
# fixes it — from understanding to pull request
# ================================================================
# 
# SETUP:
#   pip install PyGithub google-generativeai python-dotenv
#
# .env file:
#   GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
#   GITHUB_REPO=yourusername/your-repo-name
#   GEMINI_API_KEY=AIzaSy-xxxxxxxxxxxxxxxxxxxx
# ================================================================

import os
import json
import base64
import time
from datetime import datetime
from dotenv import load_dotenv
import google.generativeai as genai
from github import Github, Auth, InputGitTreeElement

load_dotenv()

# ── Configuration ──────────────────────────────────────────────
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")
GITHUB_REPO   = os.getenv("GITHUB_REPO")   # format: "username/repo-name"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ── Initialize clients ─────────────────────────────────────────
gh = None
repo = None


def configure_clients(repo_full_name: str | None = None):
    """
    Initializes external clients lazily so the CLI and API can choose the
    repository at runtime.
    """
    global GITHUB_REPO, gh, repo

    if repo_full_name:
        GITHUB_REPO = repo_full_name.strip()

    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN not set in .env file")
    if not GITHUB_REPO:
        raise ValueError("GITHUB_REPO not set in .env file or request body (format: username/repo)")
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set in .env file")

    genai.configure(api_key=GEMINI_API_KEY)
    gh = Github(auth=Auth.Token(GITHUB_TOKEN))
    repo = gh.get_repo(GITHUB_REPO)
    return repo


# ================================================================
# CORE LLM ENGINE
# Every agent that needs AI thinking calls this same function.
# Only the system_prompt changes per agent.
# ================================================================

def call_llm(system_prompt: str, user_message: str, agent_name: str) -> str:
    """
    Universal LLM caller. Each agent gets its own fresh model
    instance = own clean context = best quality output.
    Returns plain text string.
    """
    print(f"\n  [{agent_name}] thinking...")

    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction=system_prompt
    )

    prompt = (
        f"{user_message}\n\n"
        "Respond ONLY with a valid JSON object. "
        "No markdown fences. No explanation. Just raw JSON."
    )

    response = model.generate_content(prompt)
    raw = response.text.strip()

    # Strip markdown fences if Gemini adds them
    raw = raw.replace("```json", "").replace("```", "").strip()

    # Extract JSON boundaries safely
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]

    print(f"  [{agent_name}] done ✓")
    return raw


def parse_json(raw: str, fallback: dict) -> dict:
    """Safe JSON parser — returns fallback on failure."""
    try:
        return json.loads(raw)
    except Exception as e:
        print(f"  [JSON parse error] {e}")
        return fallback


# ================================================================
# STEP 1 — ISSUE READER AGENT
#
# Uses GitHub REST API to fetch the issue.
# No LLM needed here — just pure API call.
# Gets: title, body, labels, comments, author, created date.
# ================================================================

def issue_reader_agent(issue_number: int) -> dict:
    """
    Reads a GitHub issue and returns all its data.
    
    GitHub API endpoint used:
    GET /repos/{owner}/{repo}/issues/{issue_number}
    
    Also fetches comments:
    GET /repos/{owner}/{repo}/issues/{issue_number}/comments
    """
    print(f"\n{'='*60}")
    print(f"  STEP 1: Issue Reader Agent")
    print(f"{'='*60}")

    issue = repo.get_issue(number=issue_number)

    # Fetch all comments on the issue
    comments = []
    for comment in issue.get_comments():
        comments.append({
            "author": comment.user.login,
            "body": comment.body,
            "created_at": str(comment.created_at)
        })

    # Fetch labels
    labels = [label.name for label in issue.labels]

    issue_data = {
        "number":     issue.number,
        "title":      issue.title,
        "body":       issue.body or "",
        "state":      issue.state,
        "author":     issue.user.login,
        "labels":     labels,
        "comments":   comments,
        "created_at": str(issue.created_at),
        "url":        issue.html_url
    }

    print(f"  Issue #{issue_number}: {issue.title}")
    print(f"  Labels: {labels}")
    print(f"  Comments: {len(comments)}")
    return issue_data


# ================================================================
# STEP 2 — ISSUE ANALYZER AGENT
#
# Uses Gemini to deeply understand what the issue is asking.
# Produces structured analysis: type, keywords, affected areas.
# This output feeds every subsequent agent.
# ================================================================

def issue_analyzer_agent(issue_data: dict) -> dict:
    """
    Analyzes the issue and produces structured understanding.
    
    Key outputs:
    - issue_type: bug / feature / refactor / docs / test
    - keywords: terms to search for in the codebase
    - affected_areas: which parts of the system likely need changes
    - complexity: simple / medium / complex
    - summary: plain English explanation of what needs to happen
    """
    print(f"\n{'='*60}")
    print(f"  STEP 2: Issue Analyzer Agent")
    print(f"{'='*60}")

    system_prompt = """
    You are an expert Software Engineering Issue Analyzer.
    Your job is to deeply understand a GitHub issue and extract
    structured information that other agents will use to fix it.
    
    Think like a senior engineer reading this issue for the first time.
    What is the CORE problem? What keywords should I search in the code?
    Which parts of the system are likely affected?
    """

    # Combine comments for context
    comments_text = ""
    for c in issue_data.get("comments", []):
        comments_text += f"\n{c['author']}: {c['body']}"

    user_message = f"""
    Analyze this GitHub issue:

    Title: {issue_data['title']}
    Labels: {', '.join(issue_data['labels'])}
    
    Description:
    {issue_data['body']}
    
    Comments:
    {comments_text if comments_text else 'No comments'}

    Return JSON:
    {{
        "issue_type": "bug | feature | refactor | docs | test",
        "severity": "critical | high | medium | low",
        "summary": "2-3 sentence plain English summary of what needs to be done",
        "root_cause": "what is likely causing this issue",
        "keywords": ["keyword1", "keyword2", "keyword3"],
        "affected_areas": ["area1", "area2"],
        "files_likely_involved": ["hint about file types or names"],
        "complexity": "simple | medium | complex",
        "approach": "brief description of the fix approach"
    }}
    """

    time.sleep(62)  # to avoid hitting rate limits
    raw    = call_llm(system_prompt, user_message, "Issue Analyzer")
    result = parse_json(raw, {
        "issue_type": "bug",
        "severity": "medium",
        "summary": issue_data["title"],
        "root_cause": "unknown",
        "keywords": issue_data["title"].lower().split(),
        "affected_areas": ["unknown"],
        "files_likely_involved": [],
        "complexity": "medium",
        "approach": "Investigate and fix"
    })

    print(f"  Issue type  : {result.get('issue_type')}")
    print(f"  Severity    : {result.get('severity')}")
    print(f"  Complexity  : {result.get('complexity')}")
    print(f"  Keywords    : {result.get('keywords')}")
    return result


# ================================================================
# STEP 3 — REPO EXPLORER AGENT
#
# Uses GitHub API to get the FULL file tree of the repository.
# Fetches recursively so we get every single file path.
# No LLM needed — pure API call.
# ================================================================

def repo_explorer_agent() -> dict:
    """
    Fetches the complete file structure of the repository.
    
    GitHub API endpoint used:
    GET /repos/{owner}/{repo}/git/trees/{sha}?recursive=1
    
    Returns a flat list of all file paths + the default branch name.
    Filters out binary files and common non-code directories.
    """
    print(f"\n{'='*60}")
    print(f"  STEP 3: Repo Explorer Agent")
    print(f"{'='*60}")

    # Get default branch and its latest commit SHA
    default_branch = repo.default_branch
    branch_ref     = repo.get_branch(default_branch)
    tree_sha       = branch_ref.commit.sha

    # Fetch the complete recursive file tree
    git_tree = repo.get_git_tree(sha=tree_sha, recursive=True)

    # Filter to code files only (skip binaries, build artifacts, etc.)
    skip_patterns = [
        '.git/', 'node_modules/', '__pycache__/', '.pyc',
        'venv/', '.env', 'dist/', 'build/', '.jpg', '.png',
        '.gif', '.ico', '.svg', '.pdf', '.zip', '.tar',
        'package-lock.json', 'yarn.lock', '.min.js', '.min.css'
    ]

    all_files = []
    for item in git_tree.tree:
        if item.type == "blob":  # blob = file (not directory)
            skip = any(pattern in item.path for pattern in skip_patterns)
            if not skip:
                all_files.append(item.path)

    print(f"  Default branch : {default_branch}")
    print(f"  Total files    : {len(all_files)}")

    # Show a sample
    if all_files:
        print(f"  Sample files   : {all_files[:5]}")

    return {
        "default_branch": default_branch,
        "base_sha": tree_sha,
        "all_files": all_files,
        "total_files": len(all_files)
    }


# ================================================================
# STEP 4 — FILE LOCATOR AGENT
#
# Uses Gemini to match the issue keywords against the file list.
# This is purely an LLM reasoning task — no API needed.
# 
# KEY CHALLENGE: The file list can be hundreds of files.
# We send them all to the LLM and ask it to pick the most relevant.
# ================================================================

def file_locator_agent(analysis: dict, repo_structure: dict) -> dict:
    """
    Identifies which files need to be changed to fix the issue.
    
    Approach:
    - Send the issue summary + keywords + ALL file paths to Gemini
    - Gemini reasons about which files are relevant
    - Returns ranked list of files to inspect
    """
    print(f"\n{'='*60}")
    print(f"  STEP 4: File Locator Agent")
    print(f"{'='*60}")

    system_prompt = """
    You are an expert Code Navigation Agent.
    Given a GitHub issue description and a list of all files in a repository,
    identify which files are most likely relevant to the issue.
    
    Think like a senior engineer who knows the codebase well.
    Consider: file names, directory structure, typical code organization.
    Be conservative — only select files that are VERY likely to need changes.
    Maximum 5 files.
    """

    all_files = repo_structure["all_files"]

    # If repo is huge, send in chunks and let LLM pick from all
    files_text = "\n".join(all_files[:300])  # limit to 300 files

    user_message = f"""
    Issue Summary: {analysis['summary']}
    Issue Type: {analysis['issue_type']}
    Keywords: {', '.join(analysis['keywords'])}
    Affected Areas: {', '.join(analysis['affected_areas'])}
    Files likely involved hints: {', '.join(analysis.get('files_likely_involved', []))}

    All files in repository:
    {files_text}

    Return JSON:
    {{
        "files_to_read": [
            {{
                "path": "exact/path/to/file.py",
                "reason": "why this file is relevant",
                "confidence": "high | medium | low"
            }}
        ],
        "search_strategy": "brief explanation of how you identified these files"
    }}
    
    Only include files that EXIST in the list above.
    Maximum 5 files.
    """

    raw    = call_llm(system_prompt, user_message, "File Locator")
    result = parse_json(raw, {"files_to_read": [], "search_strategy": ""})

    files = result.get("files_to_read", [])
    print(f"  Files identified: {len(files)}")
    for f in files:
        print(f"    [{f.get('confidence', '?')}] {f.get('path')} — {f.get('reason', '')[:60]}")

    return result


# ================================================================
# STEP 5 — CODE READER AGENT
#
# Fetches the actual content of each identified file.
# Uses GitHub API to get file contents (returned as base64).
# No LLM needed — pure API calls.
# ================================================================

def code_reader_agent(files_to_read: list) -> dict:
    """
    Reads the content of each file identified by the File Locator.
    
    GitHub API endpoint used:
    GET /repos/{owner}/{repo}/contents/{path}
    
    Returns: dict of {file_path: file_content}
    Also captures the file SHA (needed for commit step).
    """
    print(f"\n{'='*60}")
    print(f"  STEP 5: Code Reader Agent")
    print(f"{'='*60}")

    file_contents  = {}  # path → content string
    file_shas      = {}  # path → sha (needed for update commits)

    for file_info in files_to_read:
        path = file_info.get("path", "")
        if not path:
            continue

        try:
            # GitHub returns file content as base64 encoded
            content_file = repo.get_contents(path)
            content_str  = content_file.decoded_content.decode("utf-8")

            file_contents[path] = content_str
            file_shas[path]     = content_file.sha

            lines = content_str.count('\n') + 1
            print(f"  Read: {path} ({lines} lines)")

        except Exception as e:
            print(f"  Could not read {path}: {e}")

    return {
        "file_contents": file_contents,
        "file_shas": file_shas
    }


# ================================================================
# STEP 6 — SOLUTION DESIGNER AGENT
#
# Before writing any code, the agent designs the solution.
# This is the "think before you act" step.
# Produces a detailed implementation plan.
# ================================================================

def solution_designer_agent(analysis: dict, file_contents: dict) -> dict:
    """
    Designs the solution BEFORE writing any code.
    
    This is crucial — rushing straight to code without a plan
    produces bad results. This agent creates a spec first.
    
    Output: detailed plan of what to change in each file.
    """
    print(f"\n{'='*60}")
    print(f"  STEP 6: Solution Designer Agent")
    print(f"{'='*60}")

    system_prompt = """
    You are a Senior Software Architect designing a solution.
    Your job is to create a detailed implementation plan BEFORE any code is written.
    
    Analyze the issue and the existing code carefully.
    Design the minimal, cleanest change that solves the problem.
    Explain exactly what needs to change and why.
    Do NOT write code yet — just the plan.
    """

    # Build context with file contents
    files_context = ""
    for path, content in file_contents.items():
        # Truncate very long files
        lines = content.split('\n')
        truncated = '\n'.join(lines[:150])
        if len(lines) > 150:
            truncated += f"\n... ({len(lines) - 150} more lines truncated)"
        files_context += f"\n\n--- FILE: {path} ---\n{truncated}"

    user_message = f"""
    Issue to fix:
    Type: {analysis['issue_type']}
    Summary: {analysis['summary']}
    Root cause: {analysis['root_cause']}
    Approach: {analysis['approach']}

    Current code in relevant files:
    {files_context}

    Design the solution. Return JSON:
    {{
        "solution_summary": "2-3 sentence explanation of the fix",
        "changes_needed": [
            {{
                "file": "path/to/file.py",
                "change_type": "modify | create | delete",
                "what_to_change": "specific description of the change",
                "why": "reason this change is needed",
                "affected_functions": ["function1", "function2"]
            }}
        ],
        "new_files_needed": ["path/to/new/file.py"],
        "risk_level": "low | medium | high",
        "testing_notes": "what needs to be tested after the fix"
    }}
    """

    time.sleep(30)
    raw    = call_llm(system_prompt, user_message, "Solution Designer")
    result = parse_json(raw, {
        "solution_summary": analysis["approach"],
        "changes_needed": [],
        "new_files_needed": [],
        "risk_level": "medium",
        "testing_notes": "Manual testing required"
    })

    print(f"  Solution: {result.get('solution_summary', '')[:80]}...")
    print(f"  Files to change: {len(result.get('changes_needed', []))}")
    print(f"  Risk level: {result.get('risk_level')}")
    return result


# ================================================================
# STEP 7 — CODE WRITER AGENT
#
# The actual code writing step.
# Uses the solution design + original file contents to write fixes.
# Writes complete new versions of each file.
# ================================================================

def code_writer_agent(
    analysis: dict,
    solution: dict,
    file_contents: dict
) -> dict:
    """
    Writes the actual code changes.
    
    For each file that needs changing:
    - Sends the original file content to Gemini
    - Sends the solution design
    - Asks Gemini to write the complete updated file
    
    Returns: dict of {file_path: new_content}
    """
    print(f"\n{'='*60}")
    print(f"  STEP 7: Code Writer Agent")
    print(f"{'='*60}")

    system_prompt = """
    You are an expert Software Engineer writing code to fix a GitHub issue.
    
    CRITICAL RULES:
    - Write COMPLETE file contents (not just the changed parts)
    - Preserve all existing functionality you are not changing
    - Follow the exact same code style as the existing file
    - Add clear comments explaining what you changed and why
    - Make the MINIMAL change needed to fix the issue
    - Do NOT add unnecessary features or refactoring
    """

    written_files = {}  # path → new content
    changes_needed = solution.get("changes_needed", [])

    for change in changes_needed:
        file_path   = change.get("file", "")
        change_type = change.get("change_type", "modify")
        what_to_do  = change.get("what_to_change", "")

        print(f"\n  Writing: {file_path}")

        if change_type == "delete":
            written_files[file_path] = None  # None signals deletion
            print(f"    → Marked for deletion")
            continue

        # Get original content if file exists
        original_content = file_contents.get(file_path, "")

        if change_type == "create":
            original_content = "# New file"

        user_message = f"""
        Fix this GitHub issue by modifying the code:

        Issue: {analysis['summary']}
        Root cause: {analysis['root_cause']}

        Change needed in this file:
        {what_to_do}

        Functions affected: {', '.join(change.get('affected_functions', []))}

        Original file content:
        {original_content[:3000]}
        Return JSON with the COMPLETE new file content:
        {{
            "file_path": "{file_path}",
            "new_content": "COMPLETE file content here, every single line",
            "changes_made": ["list of specific changes made"],
            "lines_changed": 5
        }}
        
        The new_content must be the ENTIRE file, not just the changed part.
        """

        raw    = call_llm(system_prompt, user_message, f"Code Writer ({file_path})")
        result = parse_json(raw, {
            "file_path": file_path,
            "new_content": original_content,
            "changes_made": [],
            "lines_changed": 0
        })

        new_content = result.get("new_content", original_content)
        written_files[file_path] = new_content

        changes_made = result.get("changes_made", [])
        print(f"    → {result.get('lines_changed', 0)} lines changed")
        for c in changes_made[:3]:
            print(f"    → {c}")

    # Handle new files from solution
    for new_file_path in solution.get("new_files_needed", []):
        if new_file_path not in written_files:
            print(f"\n  Creating new file: {new_file_path}")

            user_message = f"""
            Create a new file to help fix this issue:

            Issue: {analysis['summary']}
            File to create: {new_file_path}
            Purpose: {solution.get('solution_summary', '')}

            Return JSON:
            {{
                "file_path": "{new_file_path}",
                "new_content": "complete content of the new file",
                "changes_made": ["created new file"]
            }}
            """

            raw    = call_llm(system_prompt, user_message, f"Code Writer (new: {new_file_path})")
            result = parse_json(raw, {
                "file_path": new_file_path,
                "new_content": f"# {new_file_path}\n# Created by AI SWE Team\n"
            })

            written_files[new_file_path] = result.get("new_content", "")

    print(f"\n  Total files written: {len(written_files)}")
    return {"written_files": written_files}


# ================================================================
# STEP 8 — CODE REVIEWER AGENT
#
# Self-review step. The agent reads its own code changes
# and checks for mistakes, bugs, and missed requirements.
# This is the critique loop — catches errors before they are committed.
# ================================================================

def code_reviewer_agent(
    analysis: dict,
    written_files: dict,
    file_contents: dict
) -> dict:
    """
    Reviews the written code changes before committing.
    
    Checks for:
    - Does it actually fix the issue?
    - Did it break any existing functionality?
    - Are there syntax errors?
    - Is the code clean and readable?
    - Are there edge cases not handled?
    
    Returns: approved files OR files with corrections applied.
    """
    print(f"\n{'='*60}")
    print(f"  STEP 8: Code Reviewer Agent")
    print(f"{'='*60}")

    system_prompt = """
    You are a strict Senior Code Reviewer doing a final check before merging.
    
    Your job: review code changes critically.
    - Does this actually fix the stated issue?
    - Are there syntax errors or obvious bugs?
    - Does it break anything else?
    - Is it clean and follows good practices?
    
    If you find issues, provide the corrected code.
    Be strict but practical — approve if it's good enough.
    """

    approved_files = {}

    for file_path, new_content in written_files.items():
        if new_content is None:
            approved_files[file_path] = None  # deletions pass through
            continue

        original_content = file_contents.get(file_path, "")
        print(f"\n  Reviewing: {file_path}")

        user_message = f"""
        Review these code changes for the issue:
        
        Issue being fixed: {analysis['summary']}
        Issue type: {analysis['issue_type']}

        ORIGINAL CODE:

        {original_content[:2000]}

        NEW CODE (to be committed):
        {new_content[:3000]}


        Review and return JSON:
        {{
            "approved": true,
            "issues_found": ["issue 1", "issue 2"],
            "fixes_applied": ["fix 1", "fix 2"],
            "final_code": "final approved code (corrected if needed, original if ok)",
            "review_notes": "brief review summary",
            "confidence": "high | medium | low"
        }}
        
        The final_code must be the COMPLETE file content.
        """

        raw    = call_llm(system_prompt, user_message, f"Code Reviewer ({file_path})")
        result = parse_json(raw, {
            "approved": True,
            "issues_found": [],
            "fixes_applied": [],
            "final_code": new_content,
            "review_notes": "Approved",
            "confidence": "medium"
        })

        approved = result.get("approved", True)
        issues   = result.get("issues_found", [])
        fixes    = result.get("fixes_applied", [])
        confidence = result.get("confidence", "medium")

        print(f"    Approved  : {approved}")
        print(f"    Confidence: {confidence}")
        if issues:
            print(f"    Issues    : {issues[:2]}")
        if fixes:
            print(f"    Fixes     : {fixes[:2]}")

        # Use the reviewed/corrected code
        final_code = result.get("final_code", new_content)
        approved_files[file_path] = final_code if final_code else new_content

    print(f"\n  Review complete. {len(approved_files)} files approved.")
    return {"approved_files": approved_files}


# ================================================================
# STEP 9 — TEST WRITER AGENT
#
# Writes unit tests for the changed functions.
# Tests are committed alongside the fix.
# This dramatically increases the quality of your PRs.
# ================================================================

def test_writer_agent(analysis: dict, solution: dict, written_files: dict) -> dict:
    """
    Writes unit tests for the changes made.
    
    For each changed file, generates a corresponding test file.
    Tests cover:
    - The happy path (fix works correctly)
    - The edge cases (boundary conditions)
    - Regression cases (old bug doesn't come back)
    """
    print(f"\n{'='*60}")
    print(f"  STEP 9: Test Writer Agent")
    print(f"{'='*60}")

    system_prompt = """
    You are an expert Test Engineer writing unit tests.
    
    Write tests that:
    1. Verify the bug fix works correctly
    2. Test edge cases (empty inputs, None values, boundaries)
    3. Ensure existing functionality still works (regression tests)
    
    Use pytest style for Python, Jest for JS, JUnit for Java.
    Keep tests clear and well-documented.
    """

    test_files = {}

    for file_path, content in written_files.items():
        if content is None or not content:
            continue

        # Determine test file path convention
        if file_path.endswith(".py"):
            dir_part  = "/".join(file_path.split("/")[:-1])
            file_name = file_path.split("/")[-1]
            test_path = f"tests/test_{file_name}" if dir_part == "" else f"tests/test_{file_name}"
        elif file_path.endswith(".js") or file_path.endswith(".ts"):
            test_path = file_path.replace(".js", ".test.js").replace(".ts", ".test.ts")
        else:
            continue  # skip non-code files

        print(f"\n  Writing tests for: {file_path}")
        print(f"  Test file: {test_path}")

        affected_fns = []
        for change in solution.get("changes_needed", []):
            if change.get("file") == file_path:
                affected_fns = change.get("affected_functions", [])

        user_message = f"""
        Write unit tests for this code fix:

        Issue fixed: {analysis['summary']}
        File changed: {file_path}
        Functions affected: {', '.join(affected_fns) if affected_fns else 'see code'}

        New code:
        {content[:2500]}

        Return JSON:
        {{
            "test_file_path": "{test_path}",
            "test_content": "complete test file content",
            "test_cases": [
                "brief description of each test case"
            ]
        }}
        """
        time.sleep(62)
        raw    = call_llm(system_prompt, user_message, f"Test Writer ({file_path})")
        result = parse_json(raw, {
            "test_file_path": test_path,
            "test_content": f"# Tests for {file_path}\n# TODO: add tests\n",
            "test_cases": []
        })

        test_content = result.get("test_content", "")
        if test_content:
            test_files[test_path] = test_content
            test_cases = result.get("test_cases", [])
            print(f"    Test cases: {len(test_cases)}")
            for tc in test_cases[:3]:
                print(f"    → {tc}")

    print(f"\n  Total test files created: {len(test_files)}")
    return {"test_files": test_files}


# ================================================================
# STEP 10 — GIT COMMIT AGENT
#
# This is the most technical step.
# Uses GitHub's Git Data API to:
# 1. Create a new branch from main
# 2. Create blobs (file contents)
# 3. Create a tree (file structure)
# 4. Create a commit pointing to that tree
# 5. Update the branch reference to point to the new commit
#
# This is equivalent to: git checkout -b branch && git add . && git commit
# ================================================================

def git_commit_agent(
    issue_data: dict,
    analysis: dict,
    approved_files: dict,
    test_files: dict,
    repo_structure: dict
) -> dict:
    """
    Creates a branch and commits all changes to GitHub.
    
    GitHub Git Data API endpoints used:
    
    1. Create reference (branch):
       POST /repos/{owner}/{repo}/git/refs
       Body: {"ref": "refs/heads/branch-name", "sha": "base_sha"}
    
    2. Create blob (file content):
       POST /repos/{owner}/{repo}/git/blobs
       Body: {"content": "...", "encoding": "utf-8"}
    
    3. Create tree (file structure):
       POST /repos/{owner}/{repo}/git/trees
       Body: {"base_tree": "sha", "tree": [...]}
    
    4. Create commit:
       POST /repos/{owner}/{repo}/git/commits
       Body: {"message": "...", "tree": "sha", "parents": ["sha"]}
    
    5. Update branch reference:
       PATCH /repos/{owner}/{repo}/git/refs/heads/{branch}
       Body: {"sha": "new_commit_sha"}
    """
    print(f"\n{'='*60}")
    print(f"  STEP 10: Git Commit Agent")
    print(f"{'='*60}")

    issue_num = issue_data["number"]
    issue_type = analysis.get("issue_type", "fix")

    # Create branch name: fix/issue-42-short-description
    short_title = (
        issue_data["title"]
        .lower()
        .replace(" ", "-")
        .replace("/", "-")
        .replace(".", "")
        [:40]  # max 40 chars
    )
    branch_name = f"{issue_type}/issue-{issue_num}-{short_title}"
    # Clean branch name — remove special characters
    branch_name = "".join(c for c in branch_name if c.isalnum() or c in "-_/")

    print(f"  Branch name: {branch_name}")

    # ── STEP 10a: Create the new branch ───────────────────────
    base_sha = repo_structure["base_sha"]

    try:
        repo.create_git_ref(
            ref=f"refs/heads/{branch_name}",
            sha=base_sha
        )
        print(f"  Branch created: {branch_name}")
    except Exception as e:
        if "already exists" in str(e):
            print(f"  Branch already exists, using it")
        else:
            raise e

    # ── STEP 10b: Combine all files to commit ─────────────────
    all_changes = {}
    all_changes.update(approved_files)
    all_changes.update(test_files)

    # ── STEP 10c: Create blobs and tree elements ───────────────
    # A "blob" is git-speak for file content
    # A "tree" is git-speak for directory structure
    print(f"\n  Creating git objects for {len(all_changes)} files...")

    tree_elements = []
    for file_path, content in all_changes.items():
        if content is None:
            # Deletion — add tree element with sha=None
            tree_elements.append(
                InputGitTreeElement(
                    path=file_path,
                    mode="100644",
                    type="blob",
                    sha=None  # None = delete this file
                )
            )
            print(f"  Deleting: {file_path}")
        else:
            # Create a blob for this file's content
            blob = repo.create_git_blob(content, "utf-8")
            tree_elements.append(
                InputGitTreeElement(
                    path=file_path,
                    mode="100644",  # regular file
                    type="blob",
                    sha=blob.sha
                )
            )
            print(f"  Staged  : {file_path} (blob: {blob.sha[:8]}...)")

    # ── STEP 10d: Create the tree ──────────────────────────────
    # Get current tree of the branch as base
    base_tree = repo.get_git_tree(sha=base_sha)
    new_tree  = repo.create_git_tree(tree_elements, base_tree)
    print(f"\n  New tree SHA: {new_tree.sha[:12]}...")

    # ── STEP 10e: Create the commit ────────────────────────────
    # Commit message follows Conventional Commits format
    commit_message = (
        f"{issue_type}(#{issue_num}): {issue_data['title']}\n\n"
        f"{analysis.get('summary', '')}\n\n"
        f"Changes made:\n"
    )
    for file_path in approved_files:
        commit_message += f"- Modified {file_path}\n"
    for file_path in test_files:
        commit_message += f"- Added tests in {file_path}\n"
    commit_message += f"\nFixes #{issue_num}"

    parent_commit = repo.get_git_commit(sha=base_sha)
    new_commit    = repo.create_git_commit(
        message=commit_message,
        tree=new_tree,
        parents=[parent_commit]
    )
    print(f"  Commit SHA: {new_commit.sha[:12]}...")

    # ── STEP 10f: Update branch to point to new commit ─────────
    branch_ref = repo.get_git_ref(f"heads/{branch_name}")
    branch_ref.edit(sha=new_commit.sha)
    print(f"  Branch updated → {new_commit.sha[:12]}")

    return {
        "branch_name": branch_name,
        "commit_sha": new_commit.sha,
        "files_committed": list(all_changes.keys())
    }


# ================================================================
# STEP 11 — PULL REQUEST CREATOR AGENT
#
# Creates the final pull request on GitHub.
# Writes a detailed, professional PR description.
# Adds labels, links to the issue, and tags reviewers.
# ================================================================

def pr_creator_agent(
    issue_data: dict,
    analysis: dict,
    solution: dict,
    commit_data: dict,
    repo_structure: dict
) -> dict:
    """
    Creates a Pull Request on GitHub.
    
    GitHub API endpoint used:
    POST /repos/{owner}/{repo}/pulls
    Body: {
        "title": "...",
        "body": "...",
        "head": "branch-name",
        "base": "main"
    }
    
    Also adds a comment to the original issue linking to the PR.
    """
    print(f"\n{'='*60}")
    print(f"  STEP 11: PR Creator Agent")
    print(f"{'='*60}")

    system_prompt = """
    You are a senior engineer writing a professional Pull Request description.
    
    A great PR description includes:
    - What the issue was
    - What the root cause was
    - What changes were made and why
    - How to test the changes
    - Any risks or side effects
    - Screenshots or examples if relevant
    
    Write in a clear, professional tone. Use markdown formatting.
    """

    user_message = f"""
    Write a Pull Request description for this fix:

    Issue #{issue_data['number']}: {issue_data['title']}
    Issue type: {analysis['issue_type']}
    Severity: {analysis['severity']}
    
    Summary of the fix: {analysis['summary']}
    Root cause: {analysis['root_cause']}
    Solution: {solution['solution_summary']}
    
    Files changed: {', '.join(commit_data['files_committed'])}
    Risk level: {solution['risk_level']}
    Testing notes: {solution['testing_notes']}

    Return JSON:
    {{
        "pr_title": "concise PR title starting with type(#issue): description",
        "pr_body": "complete markdown PR description",
        "labels_to_add": ["bug", "automated-fix"]
    }}
    """

    raw    = call_llm(system_prompt, user_message, "PR Creator")
    result = parse_json(raw, {
        "pr_title": f"{analysis['issue_type']}(#{issue_data['number']}): {issue_data['title']}",
        "pr_body": f"Fixes #{issue_data['number']}\n\n{solution['solution_summary']}",
        "labels_to_add": []
    })

    pr_title  = result.get("pr_title",  f"Fix #{issue_data['number']}: {issue_data['title']}")
    pr_body   = result.get("pr_body",   f"Fixes #{issue_data['number']}")
    branch    = commit_data["branch_name"]
    base      = repo_structure["default_branch"]

    # ── Create the Pull Request ────────────────────────────────
    print(f"\n  Creating PR: {pr_title}")
    print(f"  Branch: {branch} → {base}")

    pr = repo.create_pull(
        title=pr_title,
        body=pr_body,
        head=branch,
        base=base,
        draft=False   # set True to create as draft PR
    )

    print(f"  PR created: #{pr.number}")
    print(f"  URL: {pr.html_url}")

    # ── Add labels to PR ───────────────────────────────────────
    labels_to_add = result.get("labels_to_add", [])
    if labels_to_add:
        try:
            existing_label_names = [l.name for l in repo.get_labels()]
            valid_labels = [l for l in labels_to_add if l in existing_label_names]
            if valid_labels:
                pr.add_to_labels(*valid_labels)
                print(f"  Labels added: {valid_labels}")
        except Exception as e:
            print(f"  Could not add labels: {e}")

    # ── Comment on the original issue linking to PR ────────────
    try:
        issue = repo.get_issue(number=issue_data["number"])
        issue.create_comment(
            f"🤖 **AI SWE Team** has created a pull request to fix this issue.\n\n"
            f"→ PR #{pr.number}: [{pr_title}]({pr.html_url})\n\n"
            f"**Changes made:**\n"
            + "\n".join(f"- `{f}`" for f in commit_data["files_committed"])
            + f"\n\n**Review and merge when ready.**"
        )
        print(f"  Comment added to issue #{issue_data['number']}")
    except Exception as e:
        print(f"  Could not comment on issue: {e}")

    return {
        "pr_number": pr.number,
        "pr_url": pr.html_url,
        "pr_title": pr_title,
        "branch": branch
    }


# ================================================================
# ORCHESTRATOR
#
# This is the master controller.
# It calls all 11 agents in the right order,
# passes outputs between them,
# and handles errors gracefully.
# ================================================================

def run_swe_team(issue_number: int, repo_full_name: str | None = None) -> dict:
    """
    The main orchestrator that runs the full AI SWE Team pipeline.
    
    Takes a GitHub issue number and autonomously:
    1. Reads the issue
    2. Understands it
    3. Finds relevant files
    4. Reads those files
    5. Designs a solution
    6. Writes the fix
    7. Reviews the fix
    8. Writes tests
    9. Commits everything
    10. Opens a pull request
    
    Args:
        issue_number: The GitHub issue number to fix
    
    Returns:
        dict with PR URL and summary of what was done
    """
    configure_clients(repo_full_name)
    start_time = datetime.now()

    print("\n" + "█"*60)
    print("  AI SOFTWARE ENGINEERING TEAM")
    print(f"  Fixing GitHub Issue #{issue_number}")
    print(f"  Repo: {GITHUB_REPO}")
    print("█"*60)

    results = {}
    errors  = {}

    try:
        # ── STEP 1: Read the issue ─────────────────────────────
        issue_data = issue_reader_agent(issue_number)
        results["issue"] = issue_data

        # Small delay to be nice to APIs
        time.sleep(1)

        # ── STEP 2: Analyze the issue ──────────────────────────
        analysis = issue_analyzer_agent(issue_data)
        results["analysis"] = analysis
        time.sleep(1)

        # ── STEP 3: Explore the repository ────────────────────
        repo_structure = repo_explorer_agent()
        results["repo_structure"] = repo_structure
        time.sleep(1)

        # ── STEP 4: Locate relevant files ─────────────────────
        file_locations = file_locator_agent(analysis, repo_structure)
        files_to_read  = file_locations.get("files_to_read", [])
        results["file_locations"] = file_locations

        if not files_to_read:
            print("\n  WARNING: No files identified. Cannot proceed.")
            return {"error": "No relevant files found", "issue": issue_data}

        time.sleep(1)

        # ── STEP 5: Read file contents ─────────────────────────
        code_data = code_reader_agent(files_to_read)
        file_contents = code_data["file_contents"]
        results["code_data"] = code_data

        if not file_contents:
            print("\n  WARNING: Could not read any files.")
            return {"error": "Could not read files", "issue": issue_data}

        time.sleep(1)

        # ── STEP 6: Design the solution ────────────────────────
        solution = solution_designer_agent(analysis, file_contents)
        results["solution"] = solution
        time.sleep(1)

        # ── STEP 7: Write the code ─────────────────────────────
        code_written = code_writer_agent(analysis, solution, file_contents)
        written_files = code_written["written_files"]
        results["code_written"] = code_written

        if not written_files:
            print("\n  WARNING: No files were written.")
            return {"error": "Code writing failed", "issue": issue_data}

        time.sleep(1)

        # ── STEP 8: Review the code ────────────────────────────
        review_result = code_reviewer_agent(analysis, written_files, file_contents)
        approved_files = review_result["approved_files"]
        results["review"] = review_result
        time.sleep(1)

        # ── STEP 9: Write tests ────────────────────────────────
        test_result = test_writer_agent(analysis, solution, approved_files)
        test_files  = test_result["test_files"]
        results["tests"] = test_result
        time.sleep(1)

        # ── STEP 10: Commit to GitHub ──────────────────────────
        commit_data = git_commit_agent(
            issue_data,
            analysis,
            approved_files,
            test_files,
            repo_structure
        )
        results["commit"] = commit_data
        time.sleep(1)

        # ── STEP 11: Create Pull Request ───────────────────────
        pr_data = pr_creator_agent(
            issue_data,
            analysis,
            solution,
            commit_data,
            repo_structure
        )
        results["pr"] = pr_data

    except Exception as e:
        print(f"\n  ERROR: {e}")
        import traceback
        traceback.print_exc()
        errors["fatal"] = str(e)

    # ── Final Summary ──────────────────────────────────────────
    elapsed = (datetime.now() - start_time).seconds

    print("\n" + "█"*60)
    print("  PIPELINE COMPLETE")
    print("█"*60)
    print(f"  Time elapsed: {elapsed} seconds")

    if "pr" in results:
        pr = results["pr"]
        print(f"\n  ✅ SUCCESS")
        print(f"  PR #{pr['pr_number']}: {pr['pr_title']}")
        print(f"  URL: {pr['pr_url']}")
        print(f"  Branch: {pr['branch']}")
        print(f"\n  Files changed:")
        for f in results["commit"]["files_committed"]:
            print(f"    → {f}")
    else:
        print(f"\n  ❌ Pipeline did not complete. Errors: {errors}")

    return {
        "success": "pr" in results,
        "results": results,
        "errors": errors,
        "elapsed_seconds": elapsed
    }


# ================================================================
# ENTRY POINT
# ================================================================

if __name__ == "__main__":

    # ── STEP 0: Verify configuration ──────────────────────────
    print("Checking configuration...")

    if not GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN not set in .env file")
    if not GITHUB_REPO:
        raise ValueError("GITHUB_REPO not set in .env file (format: username/repo)")
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY not set in .env file")

    print(f"Repo  : {GITHUB_REPO}")
    print(f"GitHub: {'✓' if GITHUB_TOKEN else '✗'}")
    print(f"Gemini: {'✓' if GEMINI_API_KEY else '✗'}")

    # ── Run the pipeline ───────────────────────────────────────
    # Change this to any open issue number in your repository
    ISSUE_NUMBER = 3

    result = run_swe_team(issue_number=ISSUE_NUMBER)

    # Save full results to JSON for debugging
    with open(f"swe_team_result_issue_{ISSUE_NUMBER}.json", "w") as f:
        # Remove large code contents from saved results to keep file small
        save_result = {
            "success": result["success"],
            "elapsed": result["elapsed_seconds"],
            "pr": result["results"].get("pr", {}),
            "analysis": result["results"].get("analysis", {}),
            "files_changed": result["results"].get("commit", {}).get("files_committed", []),
            "errors": result["errors"]
        }
        json.dump(save_result, f, indent=2, default=str)

    print(f"\nFull results saved to: swe_team_result_issue_{ISSUE_NUMBER}.json")
