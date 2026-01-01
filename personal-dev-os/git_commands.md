# Git Playbook

Solo development quick reference
Rule: Check → Commit → Recover

--- 
### Status & Diff

```
git status
git diff
git diff --staged
git diff <file>

# previous commit vs current working tree
git difftool -t vimdiff app.py 
```
•	diff 화면 종료: q

---

### Stage & Commit
```
git add <file>
git add docs/
git commit -m "message"
```
### Checkpoint (before risky change)

```
git commit -am "checkpoint before Codex change"

```
---


### Push
```
git push
git push -u origin main
```
---


### Restore (Last Commit State)
```
git restore <file>
git restore .
```

### Unstage only (keep local changes)
```
git restore --staged <file>
git reset <file>
```
### Hard reset (danger)
```
git reset --hard HEAD
```

---


###Undo Commits
```
git reset --hard HEAD~1   # not pushed
git revert HEAD           # already pushed
```
---

### Safe Working Loop
```
git status
git diff
git add <file>
git diff --staged
git commit -m "msg"
git push
```
---


Notes
	•	Codex diff ≠ applied change
	•	Git commit is the single source of truth
	•	When confused → git reset --hard HEAD

---
