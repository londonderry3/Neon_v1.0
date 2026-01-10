# Git Playbook

Solo development quick reference
Rule: Check → Commit → Recover

----
### Branch 생성 및 local code update (VS code)
``` 
# 새 브랜치 생성 및 이동
git checkout -b feature/krx-api-migration

# (코드 수정 후) 변경사항 저장 및 커밋
git add .
git commit -m "feat: integrate official KRX API for trading value"

# 원격 저장소에 브랜치 푸시
git push -u origin feature/krx-api-migration

# 메인 브랜치로 이동 및 최신화
git checkout main
git pull origin main

# 내 작업 브랜치를 메인에 합치기
git merge feature/krx-api-migration

# 사용 완료한 브랜치 삭제
git branch -d feature/krx-api-migration

# 원격 메인에 반영
git push origin main
```

---
### Branch 전환 및 Codex flow
1. git fetch origin으로 코덱스 브랜치 명단 가져오기
2. git switch <코덱스-브랜치-명>로 이동
3. VS Code에서 fdr.DataReader 예외 처리 코드 수정
4. git add . -> git commit -> git push (여기서 코덱스에게 공을 넘김!)
5. 완벽하면 GitHub에서 main으로 Merge!


```
git branch -vv # 현재 Branch 확인
git fetch origin # branch list update
git switch codex/summarize-code-functionality # Branch 전환
git pull # Loading
```

1. git fetch origin으로 코덱스 브랜치 명단 가져오기
git switch <코덱스-브랜치-명>로 이동
VS Code에서 fdr.DataReader 예외 처리 코드 수정
git add . -> git commit -> git push (여기서 코덱스에게 공을 넘김!)
완벽하면 GitHub에서 main으로 Merge!

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


### Undo Commits
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
---

# Installs

```
# 260104 - pykrx error로 대체재 확인
pip install finance-datareader 
```
