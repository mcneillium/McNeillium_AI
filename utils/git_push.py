#!/usr/bin/env python3
"""
McNeillium_AI — Git Auto-Push
Commits generated content and pushes to GitHub.
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def git_push(message: str = None, config: dict = None):
    """Stage, commit, and push changes to GitHub."""
    import git

    if config is None:
        config = load_config()

    git_config = config.get("git", {})
    branch = git_config.get("branch", "main")
    prefix = git_config.get("commit_prefix", "🎬 video:")

    if not message:
        message = f"{prefix} auto-generated content {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    else:
        message = f"{prefix} {message}"

    try:
        repo = git.Repo(PROJECT_ROOT)
    except git.InvalidGitError:
        print("  ⚠️  Not a git repository. Initialising...")
        repo = git.Repo.init(PROJECT_ROOT)

        # Set up remote if URL is configured
        repo_url = os.getenv("GITHUB_REPO_URL")
        if repo_url:
            try:
                repo.create_remote("origin", repo_url)
                print(f"  🔗 Remote set: {repo_url}")
            except git.GitCommandError:
                pass  # Remote already exists

    # Stage all changes (respecting .gitignore)
    print(f"  📂 Staging changes...")
    repo.git.add(A=True)

    # Check if there are changes to commit
    if not repo.is_dirty(untracked_files=True):
        print("  ℹ️  No changes to commit.")
        return

    # Commit
    print(f"  💾 Committing: {message}")
    repo.index.commit(message)

    # Push
    if git_config.get("auto_push", True):
        try:
            origin = repo.remote("origin")
            print(f"  🚀 Pushing to {branch}...")
            origin.push(branch)
            print(f"  ✅ Pushed successfully!")
        except Exception as e:
            print(f"  ⚠️  Push failed: {e}")
            print(f"  💡 You can push manually: git push origin {branch}")
    else:
        print(f"  ℹ️  Auto-push disabled. Commit saved locally.")


def main():
    parser = argparse.ArgumentParser(description="Git commit and push")
    parser.add_argument("--message", "-m", help="Commit message")
    args = parser.parse_args()

    config = load_config()

    print("\n📤 McNeillium_AI — Git Push")
    print("=" * 50)

    git_push(message=args.message, config=config)


if __name__ == "__main__":
    main()
