# Skills 索引

整包來自 [mattpocock/skills](https://github.com/mattpocock/skills)(MIT License,授權條文見 `LICENSE-mattpocock-skills`)。

- **上游版本**:commit `84fdeffd12f2ee307994d1eb6feb48173b6e0502`(2026-08-06)
- **共 36 支**:上游 35 支,原封不動;外加 `wait-what-zh` 一支是我們自己的繁中版。
- **為什麼是攤平的**:上游用 `skills/engineering/tdd/` 這種分類巢狀結構,但 Claude Code 只認 `.claude/skills/<名稱>/SKILL.md` **單層**,巢狀的不會被載入,所以複製時攤平。分類資訊靠這份索引保留。

## ⚠️ 兩件會影響你的事

**1. 內建的 `/code-review` 被蓋掉了。** 這包裡有一支同名的 `code-review`,而專案層級的 skill 會覆蓋 Claude Code 內建版。你之後打 `/code-review` 跑的是 Matt Pocock 的版本,不是內建那支。不想要的話,刪掉資料夾就會恢復:

```
rm -rf .claude/skills/code-review
```

**2. 有 8 支 skill 會去找 `CONTEXT.md`,這個檔案本專案沒有。** 那是上游用來存「統一術語」的檔(我們的對應物是 `CLAUDE.md`)。這 8 支是 `ask-matt`、`diagnosing-bugs`、`domain-modeling`、`improve-codebase-architecture`、`setup-matt-pocock-skills`、`tdd`、`triage`、`wait-what`。要補的話跑一次:

```
/setup-matt-pocock-skills
```

## engineering(18 支,官方 plugin 內容)

| 指令 | 誰觸發 | 做什麼 |
|---|---|---|
| `/ask-matt` | 你 | 不知道該用哪支 skill 時問它,它幫你挑 |
| `/grill-with-docs` | 你 | 逼問式訪談把計畫問到清楚,同時產出 ADR 與詞彙表 |
| `/implement` | 你 | 依 spec 或 ticket 實作 |
| `/improve-codebase-architecture` | 你 | 掃描架構問題 → 出 HTML 報告 → 逼你逐項決定 |
| `/setup-matt-pocock-skills` | 你 | 把這個 repo 設定成適用整套 skill(會建 `CONTEXT.md`) |
| `/to-spec` | 你 | 把當前對話變成 spec,發到 issue tracker |
| `/to-tickets` | 你 | 把計畫拆成一顆顆可獨立完成的 ticket |
| `/triage` | 你 | issue 與外部 PR 的分流狀態機 |
| `/wayfinder` | 你 | 規劃「一個 session 裝不下」的大工程 |
| `code-review` | 模型自動 | 從指定 commit/分支起算的變更,做兩軸審查 |
| `codebase-design` | 模型自動 | 設計「深模組」時的共用詞彙 |
| `diagnosing-bugs` | 模型自動 | 難纏 bug 與效能退化的診斷循環 |
| `domain-modeling` | 模型自動 | 建立並精煉專案的領域模型 |
| `prototype` | 模型自動 | 做拋棄式原型來回答設計問題 |
| `research` | 模型自動 | 對一手來源查證,結果寫成 Markdown |
| `resolving-merge-conflicts` | 模型自動 | 解進行中的 merge / rebase 衝突 |
| `tdd` | 模型自動 | 紅 → 綠 → 重構的測試先行流程 |
| `wizard` | 模型自動 | 產生互動式 bash 精靈,帶人走只有人能做的步驟 |

## productivity(7 支,官方 plugin 內容)

| 指令 | 誰觸發 | 做什麼 |
|---|---|---|
| `/grill-me` | 你 | 逼問你的計畫,直到每個分支都有答案 |
| `/handoff` | 你 | 把當前對話壓成交接文件,給下一個 agent 接手 |
| `/teach` | 你 | 跨 session 教你一個新技能或概念 |
| `/to-questionnaire` | 你 | 把你一個人答不了的決定,變成問卷丟給能答的人 |
| `/wait-what` | 你 | 剛剛那段沒聽懂,重講(**英文原版**) |
| `/wait-what-zh` | 你 | 同上的**繁體中文版**,改指向 `CLAUDE.md` ← 平常用這支 |
| `grilling` | 模型自動 | 同 grill-me,但由模型自己判斷時機 |
| `writing-for-agents` | 模型自動 | 怎麼寫給 agent 看的文件(skill、CLAUDE.md) |

## misc(4 支,**不在**官方 plugin 內)

上游沒把這些放進 plugin。其中 3 支綁 JavaScript/TypeScript 生態,對本專案(Python + Flask)沒有用處,留著只是為了「整包」的完整性。

| 指令 | 對本專案有用嗎 | 做什麼 |
|---|---|---|
| `git-guardrails-claude-code` | ✅ 有用 | 裝 Claude Code hook,擋掉危險 git 指令(push、reset --hard、clean、branch -D) |
| `setup-pre-commit` | ❌ JS/TS 專用 | 裝 Husky + lint-staged + Prettier |
| `migrate-to-shoehorn` | ❌ TS 專用 | 把測試的 `as` 型別斷言換成 shoehorn |
| `scaffold-exercises` | ❌ 教材專用 | 產生教學練習的目錄結構 |

## in-progress(6 支,作者標明 beta)

上游原話:「公開是故意的——用用看然後告訴我哪裡壞了」,並且**可能隨時改動或消失**,不含在官方 plugin 內。

| 指令 | 做什麼 |
|---|---|
| `/claude-handoff` | 交接給背景 agent 立刻接手 |
| `/loop-me` | 逼問你把要做的 workflow 規格講清楚 |
| `/setup-ts-deep-modules` | TypeScript 專用,接 dependency-cruiser |
| `/writing-beats` | 用「節拍」把素材組成文章 |
| `/writing-fragments` | 挖出你腦中的素材碎片,存成原料 |
| `/writing-shape` | 把原料一段一段塑成文章 |

## 安全檢查(複製前做的)

- **沒有任何一支 skill 使用 `allowed-tools`**,也就是沒有人自行放寬工具權限。
- 3 支 shell 腳本(`diagnosing-bugs/scripts/hitl-loop.template.sh`、`wizard/template.sh`、`git-guardrails-claude-code/scripts/block-dangerous-git.sh`)都是範本,你不主動叫就不會跑。

## 怎麼更新

這是**複製進來的**,不會自動跟上游更新。要更新就重跑一次同樣的流程(重新 clone 上游、攤平覆蓋)。

想改用會自動更新的官方外掛方式(不佔專案空間,但每台電腦要各裝一次):

```
/plugin marketplace add mattpocock/skills
```

兩種方式擇一即可,同時裝會出現同名 skill。
