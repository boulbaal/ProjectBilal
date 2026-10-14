# The prompt

Copy everything inside the box below and paste it into Claude Cowork (or Claude Code) with this repository folder open. Nothing else is needed.

```
You are setting up ProjectBilal for my business. Work from this repository.

Read CLAUDE.md first and follow it. It defines the phases, the agents you must use for each phase, and the rules you may never break.

Then go through the phases in order:

1. INTAKE: open INTAKE.md. Ask me for every item that is missing, one group at a time, in plain language. Explain each item in one sentence before you ask. Write my answers into .env (secrets) and knowledge/ (business facts). Never put secrets anywhere except .env. Never ask me to paste a secret into chat if there is a safer way, and if there is none, tell me so I can rotate it afterwards. Confirm that .env is in .gitignore.

2. VERIFY ACCESS: before building anything, prove that the credentials work. Verify the Meta app with a test webhook, log in to the mailbox, connect to the VPS over SSH. If any check fails, stop, tell me exactly what to fix, and wait.

3. TRAIN: use the knowledge-trainer agent. Read the mailbox history and any WhatsApp chat exports I give you. Build knowledge/style.md, knowledge/faq.md and knowledge/company.md from what you find. Turn my pricing rules into knowledge/pricing/rules.yaml and verify them with the quote-calculator agent against examples I confirm. Show me what you learned and ask me to correct it before you continue.

4. CRITERIA: use the gatekeeper agent. Walk me through knowledge/escalation.md. Ask which replies must be held for human approval and who receives the approval emails. Write the final criteria into the file.

5. DEPLOY: use the deployer agent. Install the service on my VPS with HTTPS, as a system service that restarts on reboot. Register the webhook with Meta. Do not touch anything on the VPS that is not part of this project.

6. TEST: use the tester agent and tests/TEST_PLAN.md. Run every test in order with me. Do not skip a test. Do not continue past a failed test. Nothing is sent to real customers until all tests pass and I say so explicitly.

7. HANDOVER: write HANDOVER.md in this folder in my language: how to add a rule, change a price, change a criterion, read the logs, restart the service, and what to do when something breaks. Keep it short and concrete.

Rules for the whole session:
- Ask me when you are not sure. Do not guess business facts, prices, or criteria.
- Never invent prices, delivery times or promises. If it is not in knowledge/, the reply escalates to a human.
- Keep me informed in short messages. I may not be technical. Explain what you are doing in one line before you do it.
- If something in this repository does not work with my setup (different mail provider, different VPS, a changed Meta API), adapt the code and say what you changed and why.
- If the agents in .claude/agents/ are not available as agents in this environment, read each file as instructions and follow it yourself when its phase comes.
```

## If you only want to change something later

Paste this instead:

```
Read CLAUDE.md and HANDOVER.md. I want to change something in ProjectBilal: [describe the change]. Use the right agent from .claude/agents/, make the change, run the relevant tests from tests/TEST_PLAN.md with me, then redeploy with the deployer agent.
```
