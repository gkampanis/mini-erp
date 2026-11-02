# P9.2.5 — operator-controlled continuation

User-requested behavior supersedes the earlier permanent history locks. Previous queue/attempt state no longer disqualifies a new explicit posting selection. Real registration evidence and group-6-only scope remain enforced. A local attempt is still available as informative history and never proves EBS storage.

On a runtime fill/Save/New issue the document remains in the pending workspace. When later items remain, ask whether to continue: Yes leaves the failed attempt in history and advances to later queued documents on a fresh form; No pauses execution. There is no automatic retry of the failed document, and no manual history-unlock requirement for a later explicit posting action. If Save may already have been sent, the question says so. An error on the last item reports that no later items remain.

Each item is checked when its turn arrives. Later invalid/registered items do not cause healthy predecessors to be skipped. The current approved account is reread before input. A changed profile is a whole-queue configuration issue, not a failed document; all items remain queued and a new posting action uses current settings.

The selected-record batch no longer pauses automatically at 40. The separate "up to 40" action still selects at most 40, and explicit Pause/Stop remain available. Native fill order, mapped points, net editor focus guard, Save and New implementation are unchanged from P9.2.4.

Verification uses synthetic databases and fake EBS sessions for error cases. Real Tk controls and worker callbacks exercise Yes/No and pending-list behavior. No production DB or EBS writes are performed during development. A successful Windows delivery gate does not constitute live EBS posting acceptance.

Delivery infrastructure: Windows per-command allowance is 1200 seconds and the generic Tk worker wait is 30 seconds (other platforms retain their previous limits). On command timeout, terminate the launched test process tree before temporary-directory cleanup. Cleanup failure cannot replace the original check failure. Functional assertions are unchanged. This addresses observed slow Windows execution and orphaned GUI workers in the failed first P9.2.5 delivery run; no artifact from that run was published.
