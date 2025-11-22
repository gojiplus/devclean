"""Claude-powered agent for interactive disk cleanup."""

import os
from typing import Any, Dict, List, Optional

from anthropic import Anthropic
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from .tools import TOOL_DEFINITIONS, execute_tool

SYSTEM_PROMPT = """\
You are DevClean, a friendly and knowledgeable assistant that helps macOS developers clean up disk space.

## Your job
1. Scan the user's disk for developer cruft (caches, virtual environments, Docker data, etc.)
2. Explain what each item is and whether it's safe to delete
3. Help the user decide what to clean up
4. Execute deletions ONLY when the user explicitly confirms

## Workflow

### Initial scan
Always start by calling `scan_disk` to understand what's taking space. Present results grouped by category, highlighting:
- Total recoverable space
- Biggest items first
- ORPHANED items (tool uninstalled but data remains) — these are easy wins
- Items marked "caution" that need careful consideration

### Deletion flow
NEVER call `delete_directory` without explicit user confirmation. The flow is:

1. User asks to delete something → Confirm: "Delete X (Y GB)? This will [consequence]."
2. User says yes/confirm/do it → Call `delete_directory` with `use_sudo=false` first
3. If permission denied → Ask: "Permission denied. Want me to retry with sudo?"
4. User confirms sudo → Call `delete_directory` with `use_sudo=true`
5. If sudo still fails → Explain Full Disk Access (see below)

### Batch deletions
If user says "delete all safe items" or similar:
- List what will be deleted with sizes
- Get ONE confirmation for the batch
- Delete one by one, reporting progress
- If any fail, report and continue with others

### Custom paths (not in scan)
If user asks to delete a path that wasn't in the scan:
1. Inspect it with `get_directory_size` and `list_directory`
2. Call `approve_path_for_deletion` with a reason explaining what it is
3. Confirm with user
4. Then call `delete_directory`

This is a safety feature — you can only delete paths that were either found in a scan OR explicitly approved after inspection.

### Interpreting delete results
The `delete_directory` tool returns structured JSON with an "error" field:
- `PERMISSION_DENIED` → Suggest retrying with `use_sudo=true`
- `FULL_DISK_ACCESS_REQUIRED` → Guide user through System Settings
- `PATH_NOT_FOUND` → Already deleted, move on
- `PATH_NOT_SCANNED` → Need to scan first or approve the path
- `PROTECTED_PATH` → Refuse, explain why

### Permission errors — Full Disk Access flow
If deletion fails even with sudo, the path is likely protected by macOS sandbox. Explain:

"macOS is protecting this directory. To delete it:
1. Open System Settings → Privacy & Security → Full Disk Access
2. Click the + button
3. Add Terminal (or your terminal app) from /Applications/Utilities/
4. Restart your terminal
5. Try again (no sudo needed once Terminal has access)"

### Error handling
- If scan finds nothing: Celebrate! "Your system is clean."
- If a path no longer exists: "Already deleted or moved."
- If tool check fails: Proceed but note uncertainty
- If user seems unsure: Offer more explanation, don't push deletion

## Safety rules (NEVER violate these)
- NEVER delete without explicit user confirmation
- NEVER delete: ~, ~/Documents, ~/Desktop, ~/Downloads, ~/Pictures, ~/Music, /
- ALWAYS explain what an item is before offering to delete
- Items marked "caution" (safe=false) require extra confirmation and explanation
- When in doubt, don't delete — ask for clarification

## Tone
- Conversational and helpful, not robotic
- Explain technical concepts simply
- Celebrate wins ("Nice! You just freed 5GB")
- Don't be preachy about disk hygiene

Start by greeting the user briefly and offering to scan their disk.
"""


class DevCleanAgent:
    """Interactive agent for disk cleanup."""

    def __init__(self, api_key: str | None = None) -> None:
        self.client = Anthropic(api_key=api_key)
        self.console = Console()
        self.messages: list[dict[str, Any]] = []
        self.model = "claude-sonnet-4-20250514"

    def _call_claude(self) -> str:
        """Make a request to Claude and handle tool calls."""

        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,  # type: ignore
            messages=self.messages,  # type: ignore
        )

        # Process response, handling tool use
        while response.stop_reason == "tool_use":
            # Find tool use blocks
            assistant_content = response.content
            self.messages.append({"role": "assistant", "content": assistant_content})

            # Execute each tool call
            tool_results = []
            for block in assistant_content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    tool_id = block.id

                    # Show user what's happening
                    self.console.print(f"[dim]→ Running {tool_name}...[/dim]")

                    # Execute the tool
                    result = execute_tool(tool_name, tool_input)

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": result,
                        }
                    )

            # Send tool results back
            self.messages.append({"role": "user", "content": tool_results})

            # Get next response
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOL_DEFINITIONS,  # type: ignore
                messages=self.messages,  # type: ignore
            )

        # Extract final text response
        final_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                final_text += block.text

        self.messages.append({"role": "assistant", "content": response.content})

        return final_text

    def chat(self, user_message: str) -> str:
        """Send a message and get a response."""
        self.messages.append({"role": "user", "content": user_message})
        return self._call_claude()

    def run_interactive(self) -> None:
        """Run interactive chat loop."""

        self.console.print(
            Panel(
                "[bold blue]DevClean[/bold blue] - AI-powered disk cleanup for developers\n"
                "[dim]Type 'quit' or 'exit' to stop, 'help' for commands[/dim]",
                border_style="blue",
            )
        )
        self.console.print()

        # Get initial greeting/offer to scan
        response = self.chat("Hi! I'd like to clean up some disk space.")
        self.console.print(Markdown(response))
        self.console.print()

        while True:
            try:
                user_input = Prompt.ask("[bold green]You[/bold green]")
            except (KeyboardInterrupt, EOFError):
                self.console.print("\n[dim]Goodbye![/dim]")
                break

            if not user_input.strip():
                continue

            if user_input.lower() in ("quit", "exit", "q"):
                self.console.print("[dim]Goodbye![/dim]")
                break

            if user_input.lower() == "help":
                self.console.print(
                    Panel(
                        "Commands:\n"
                        "  scan      - Scan for cruft\n"
                        "  delete X  - Delete a specific path\n"
                        "  quit      - Exit\n\n"
                        "Or just chat naturally!",
                        title="Help",
                        border_style="dim",
                    )
                )
                continue

            try:
                response = self.chat(user_input)
                self.console.print()
                self.console.print(Markdown(response))
                self.console.print()
            except Exception as e:
                self.console.print(f"[red]Error: {e}[/red]")


def run_agent(api_key: str | None = None) -> None:
    """Entry point for running the agent."""
    agent = DevCleanAgent(api_key=api_key)
    agent.run_interactive()
