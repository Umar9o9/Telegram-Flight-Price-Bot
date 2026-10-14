---
name: Bot source replacements
description: How to handle user-provided full replacements for the Telegram bot script.
---

When replacing the Telegram bot script, copy the user's attached Python file byte-for-byte to `main.py`, leave all other application files unchanged, then restart the `Telegram Bot` workflow and confirm it is running.

**Why:** The user has repeatedly requested exact attachment-based replacements and no unrelated code changes.

**How to apply:** For each new attachment, confirm it is complete, copy it without transformation, compare hashes, restart the bot, and check startup status.
