# Skills 索引

主要來自 [mattpocock/skills](https://github.com/mattpocock/skills)(MIT License,授權條文見 `LICENSE-mattpocock-skills`)。

- **上游版本**:commit `84fdeffd12f2ee307994d1eb6feb48173b6e0502`(2026-08-06)
- **目前 26 支**:上游 35 支中留下 25 支,外加自製的 `wait-what-zh`。刪掉的 10 支見文末。
- **為什麼是攤平的**:上游用 `skills/engineering/tdd/` 這種分類巢狀結構,但 Claude Code 只認 `.claude/skills/<名稱>/SKILL.md` **單層**,巢狀的不會被載入,所以複製時攤平。分類資訊靠這份索引保留。
- **設定檔**:這些 skill 讀 `docs/agents/`(issue tracker、triage 標籤、領域文件規則)與根目錄的 `CONTEXT.md`(統一語彙),已由 `/setup-matt-pocock-skills` 建好。

## engineering(17 支)

| 指令 | 誰觸發 | 做什麼 |
|---|---|---|
| `/ask-matt` | 你 | 不知道該用哪支 skill 時問它,它幫你挑 |
| `/grill-with-docs` | 你 | 逼問式訪談把計畫問到清楚,同時產出 ADR 與詞彙表 |
| `/implement` | 你 | 依 spec 或 ticket 實作 |
| `/improve-codebase-architecture` | 你 | 掃描架構問題 → 出 HTML 報告 → 逼你逐項決定 |
| `/setup-matt-pocock-skills` | 你 | 設定本 repo 適用整套 skill(**已跑過**,只有要換 issue tracker 才需重跑) |
| `/to-spec` | 你 | 把當前對話變成 spec,發到 GitHub Issues |
| `/to-tickets` | 你 | 把計畫拆成一顆顆可獨立完成的 ticket |
| `/triage` | 你 | issue 與外部 PR 的分流狀態機 |
| `/wayfinder` | 你 | 規劃「一個 session 裝不下」的大工程 |
| `codebase-design` | 模型自動 | 設計「深模組」時的共用詞彙 |
| `diagnosing-bugs` | 模型自動 | 難纏 bug 與效能退化的診斷循環 |
| `domain-modeling` | 模型自動 | 維護 `CONTEXT.md` 與 ADR |
| `prototype` | 模型自動 | 做拋棄式原型來回答設計問題 |
| `research` | 模型自動 | 對一手來源查證,結果寫成 Markdown |
| `resolving-merge-conflicts` | 模型自動 | 解進行中的 merge / rebase 衝突 |
| `tdd` | 模型自動 | 紅 → 綠 → 重構的測試先行流程 |
| `wizard` | 模型自動 | 產生互動式 bash 精靈,帶人走只有人能做的步驟 |

## productivity(8 支)

| 指令 | 誰觸發 | 做什麼 |
|---|---|---|
| `/grill-me` | 你 | 逼問你的計畫,直到每個分支都有答案 |
| `/handoff` | 你 | 把當前對話壓成交接文件,給下一個 agent 接手 |
| `/teach` | 你 | 跨 session 教你一個新技能或概念 |
| `/to-questionnaire` | 你 | 把你一個人答不了的決定,變成問卷丟給能答的人 |
| `/wait-what-zh` | 你 | 剛剛那段沒聽懂,用**繁中**重講 ← 平常用這支 |
| `/wait-what` | 你 | 同上的英文原版(上游原封不動) |
| `grilling` | 模型自動 | 同 grill-me,但由模型自己判斷時機 |
| `writing-for-agents` | 模型自動 | 怎麼寫給 agent 看的文件(skill、CLAUDE.md) |

## misc(1 支)

| 指令 | 誰觸發 | 做什麼 |
|---|---|---|
| `git-guardrails-claude-code` | 模型自動 | 裝 Claude Code hook,擋掉危險 git 指令(push、reset --hard、clean、branch -D) |

## 刪掉的 10 支與原因

| 刪除的 skill | 原因 |
|---|---|
| `code-review` | 與 Claude Code 內建 `/code-review` 同名會覆蓋它;刪掉後 `/code-review` 恢復成內建版。`ask-matt`/`tdd`/`implement` 內文提到的 `/code-review` 會自動接到內建版,不會斷鏈 |
| `setup-pre-commit` | Husky + lint-staged + Prettier,JS/TS 專用 |
| `migrate-to-shoehorn` | `@total-typescript/shoehorn`,TypeScript 專用 |
| `scaffold-exercises` | 產生教學課程的練習目錄,與本專案無關 |
| `claude-handoff`、`loop-me`、`setup-ts-deep-modules`、`writing-beats`、`writing-fragments`、`writing-shape` | 上游 `in-progress/` 的 beta,作者聲明「可能隨時改動或消失」,且不含在官方 plugin 內 |

要救回任何一支,重新 clone 上游後把對應資料夾複製到 `.claude/skills/<名稱>/` 即可(記得攤平,不要帶分類層)。

## 安全檢查(安裝前做的)

- **沒有任何一支 skill 使用 `allowed-tools`**,也就是沒有人自行放寬工具權限。
- 剩下的 2 支 shell 腳本(`diagnosing-bugs/scripts/hitl-loop.template.sh`、`wizard/template.sh`)都是範本,你不主動叫就不會跑。

## 怎麼更新

這是**複製進來的**,不會自動跟上游更新。要更新就重跑一次同樣的流程(重新 clone 上游、攤平覆蓋、再刪掉上表那 10 支)。

想改用會自動更新的官方外掛方式(不佔專案空間,但每台電腦要各裝一次):

```
/plugin marketplace add mattpocock/skills
```

兩種方式擇一即可,同時裝會出現同名 skill。
